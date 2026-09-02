# FBA Order Import — Handoff

## Overview

The `fba` module (`Backend/app/modules/fba/`) is the server-side port of the
local `FBA/` pipeline (`FBA/main.py` + `FBA/get_input.py`). It replaces the old
round-trip of *"run `main.py` on a laptop → upload `final_orders_*.csv` through
the FBA CSV import"*.

Now the operator drops the **two raw Seller Central exports** into the
**Orders → FBA → Import Orders** dialog and the server does the rest:

```
All-Orders .txt  ─┐
                  ├─▶ merge ─▶ scrape missing buyer names ─▶ ingest (AMAZON_FBA_CSV path)
Fulfilment .csv  ─┘   (parsing)      (scraping)                   (ingesting)
```

It is a **manually-triggered, one-at-a-time background job** held in
module-level state — the exact pattern of the tracking scraper
(`Docs/Tracking_Scraper_Handoff.md`) and the Zoho bulk sync. The operator can
navigate away; a navbar chip + slide-out panel show progress.

The buyer-name step drives a **real (headed) Chromium** with a **persistent
profile** (Amazon needs a logged-in session), inside a virtual X display, the
same way the tracking scraper drives parcelsapp. This document is mostly about
that browser piece and how the login profile gets onto the server.

---

## 1. The pipeline — `pipeline.py`

A near-verbatim port of `FBA/main.py` steps 1–3, minus all file I/O and **minus
the `data/archive/` deduplication**:

| Step | What |
| :--- | :--- |
| Parse `all_orders.txt` | tab-delimited `csv.DictReader`, headers slugified (`Amazon Order Id` → `amazon-order-id`) |
| Filter | keep only `fulfillment-channel == amazon` **and** `order-status` starts `shipping`/`shipped` |
| Parse `fulfillment.csv` | `csv.DictReader`, headers slugified |
| Merge | `ALL_ORDER_FIELD_MAP` + `SHIPMENT_FIELD_MAP`; shipment rows matched by `merchant-order-id`, then `order-item-id`, then `sku` (`pick_shipment_matches`) |
| Output | `(fieldnames, rows)` keyed exactly like the old `final_orders_*.csv` (`order-id`, `buyer-name`, `sku`, `item-price`, …) |

`build_merged_rows(all_orders_txt, fulfillment_csv)` is pure and unit-tested
(`tests/modules/fba/test_fba_pipeline.py`). A malformed / wrong report raises
`PipelineError` → the job ends `failed` with a readable message.

### Why no archive dedupe

The ERP already dedupes on `(platform, external_order_id)` at ingest
(`OrderSyncService._ingest_order`). An order seen in a previous import is matched
by its Amazon `order-id` and **updated in place** — `_update_existing_order`
**sets** amounts and **upserts** line items (never adds), so re-importing an
overlapping date window does **not** duplicate orders, lines, or totals. Missing
buyer names on already-imported orders are back-filled on the update. This is
why the pipeline scrapes names for **every** merged row missing one, not just
"new" rows.

> Keep the reporting window small (the dialog's **period hint** picks the
> smallest "Last N days" that covers the gap since the last FBA order) — a wide
> re-import marks many orders `changed`, which can queue that many Zoho outbound
> syncs.

---

## 2. The buyer-name scraper — `scraper.py`

`FbaBuyerNameScraper` owns **one** virtual display + **persistent** Chromium
context for the whole job:

```python
scraper = FbaBuyerNameScraper(
    profile_path=settings.fba_chrome_profile_path,   # a MOUNTED volume
    headless=settings.fba_scraper_headless,          # False in prod
    host_resolver_rules=settings.fba_scraper_host_resolver_rules,  # "" in prod
)
await scraper.start()
if not await scraper.check_auth():
    raise FbaAuthExpired(...)
res = await scraper.scrape_buyer_name(order_id)      # -> BuyerNameResult(buyer_name, detail)
```

* **Persistent context**, not the ephemeral one the tracking scraper uses:
  `launch_persistent_context(user_data_dir=settings.fba_chrome_profile_path)`.
  That path is a **mounted volume** (`fba_profile`) — never baked into the image,
  never a path under `PLAYWRIGHT_BROWSERS_PATH`.
* **Headed inside `Xvfb`** (`pyvirtualdisplay`), same as tracking. Falls back to
  headless with a warning if `Xvfb` is missing (Amazon will then bounce to login
  → job finishes `completed_with_warnings`, it does not crash).
* Buyer-name extraction is the 3-attempt strategy from `FBA/main.py`:
  `[data-test-id="buyer-name-with-link"]` → `shipping-section-contact-buyer-value`
  → a tree-walker that reads the text next to "Contact Buyer".
* **The "Switch accounts" interstitial.** Seller Central's OpenID flow carries
  `openid.pape.max_auth_age=300`, so after a while Amazon stops honouring the
  cookie silently and bounces `/home` (and order pages) through an account-
  picker page (`/ap/signin?…switch_account=…`). `_settle_sso()` clicks the
  already-signed-in account tile (`a[data-name="switch_account_request"]`) to
  get past it. If that click lands on *"Please enter your password to
  continue"*, the session is stale and needs a real refresh (§7b).
* **Login detection:** after `_settle_sso()`, if the page is still on a sign-in
  URL, `scrape_buyer_name` raises `FbaAuthExpired`.
* **`check_auth()` is tri-state:** `logged_in` (landed on a real Seller Central
  page) / `signed_out` (still on a sign-in / `switch_account=auth_prompt` page
  after clicking through, or a credential field is rendered) / `unverified`
  (page genuinely wouldn't load — network). The runner only **skips** scraping
  on `signed_out`; on `unverified` it tries anyway and lets the first real
  order load be the judge.

### Result vocabulary (per order, for the UI grid)

`FOUND`, `NOT_FOUND` (page had no buyer name), `ERROR` (page/nav failure),
`SKIPPED` (no profile configured), `AUTH_EXPIRED` (session gone — the rest of the
queue is marked this and skipped).

---

## 3. Orchestration — `runner.py`

One job, module-level singletons in the worker that received the request
(`_CURRENT_JOB`, `_LAST_JOB`, `_CURRENT_TASK`, `_JOB_LOCK`) — same multi-worker
caveat as tracking (`GET /status` can briefly hit a different worker; per-item
progress is on the job object only, orders are committed at the ingest step).

`FbaImportJobState` holds `status`, `phase`, the pipeline row counts, the
`items` list (`BuyerNameItemState` per order needing a name), `counts`,
`orders_created` / `items_created`, `warnings`, `message`, `last_error`.

**Statuses:** `running` → `completed` | `completed_with_warnings` | `aborted` |
`failed`.
**Phases:** `parsing` → `scraping` → `ingesting` → `done`.

`_process(job, txt, csv)`:

1. **parsing** — `build_merged_rows()`. Build `items` = distinct `order-id`s
   whose merged row has no `buyer-name`.
2. **scraping** — `_scrape_buyer_names()`: start the scraper, `check_auth()`,
   then per item: `scrape_buyer_name` (80 s timeout), patch every row for that
   `order-id`, `sleep(random.uniform(1, 10))`. Up to
   `fba_scraper_max_attempts_per_order` (2) tries each.
   * `FbaAuthExpired` anywhere → stop, add the *"refresh the profile"* warning,
     mark all unscraped items `AUTH_EXPIRED`, **continue to step 3**.
   * A single order erroring never blocks the import.
3. **ingesting** — serialise rows → CSV text → `_parse_amazon_fba_csv()` (the
   *existing* parser, unchanged) → `ingest_parsed_rows(source="AMAZON_FBA_CSV",
   fulfillment_channel=AMAZON_FBA, skip_existing=False)` in a fresh DB session.
4. `completed_with_warnings` if `job.warnings` else `completed`.

**Abort** sets `cancel_requested`, cancels the task. Committed progress (if
ingestion already ran) stays; nothing partial is left mid-ingest because ingest
is a single call.

**No restart recovery** by design — a backend restart drops the job. Just
re-upload the same two files; the DB upsert makes it idempotent.

---

## 4. API — `routes.py`

Prefix `/api/v1/fba`. All endpoints require **ADMIN or SALES_REP**.

| Method & path | Purpose |
| :--- | :--- |
| `POST /import/start` | multipart `all_orders_txt` + `fulfillment_csv` → start a job (202; 409 if one is active) |
| `GET  /import/status` | poll — full `FbaImportJobOut` (`{status:"idle"}` if none) |
| `POST /import/abort` | stop the job |
| `GET  /import/period-hint` | recommended Seller Central "Last N days" + which button per report, from the newest FBA `ordered_at` in the DB |
| `POST /import/auth-check` | launch the profile, report `{state}` = `logged_in` / `signed_out` / `unverified` — lets the dialog warn *before* upload |

Router registered in `app/main.py` next to `tracking_router`.

---

## 5. Frontend

Mirrors the tracking trio. All under `frontend/src/`.

| File | Role |
| :--- | :--- |
| `types/fba.ts`, `api/fba.ts`, `api/endpoints.ts` (`FBA`) | mirror `schemas.py` + axios wrappers |
| `context/FbaImportContext.tsx` | one polling `useQuery(['fbaImportJob'])` (2 s while active or panel open) + panel state + start/abort mutations. Gated on `ADMIN`/`SALES_REP`. Provider mounted in `main.tsx`. |
| `components/orders/FbaOrderImportButton.tsx` | **Replaces** the CSV picker on the FBA tab. Two drag-drop zones, per-report deep link + "pick *Last N days* → click *{button}*" instructions from `/period-hint`, a "Check Seller Central login" button (`/auth-check`). `<OrderImportButton>` delegates here when `fulfillmentChannel === 'AMAZON_FBA'`. |
| `components/fba/FbaImportPanel.tsx` | right-side drawer: phase `Stepper`, buyer-name progress bar, count chips, `warnings[]` alerts, per-order `DataGrid`, Abort/Close. Mounted once in `main.tsx`. |
| `components/fba/GlobalFbaImportChip.tsx` | navbar chip while running / just-finished (5 min). In `Layout.tsx`. |
| `components/fba/FbaImportResultChip.tsx` | per-order result chip |

---

## 6. Deployment — Dockerfile & compose

**No Dockerfile browser changes** — the tracking work already added
`playwright` + `playwright-stealth` + `pyvirtualdisplay` and the builder-cached
Chromium + `xvfb`/`xauth`. This feature adds one line:

```dockerfile
RUN mkdir -p /data/fba-profile && chown -R appuser:appgroup /data
```

so a **fresh** `fba_profile` volume inherits `appuser` ownership (the persistent
context must be able to write the profile as non-root).

**`docker-compose.yml`** adds a named volume to `backend` and `backend-dev`:

```yaml
    volumes:
      - fba_profile:/data/fba-profile
# ...
volumes:
  fba_profile:
```

`.github/workflows/deploy.yml` needs no change — the volume persists across
`docker compose up -d --build`.

### Config (`app/core/config.py`, all optional)

| Setting | Default | Notes |
| :--- | :--- | :--- |
| `fba_chrome_profile_path` | `/data/fba-profile` | the mounted volume |
| `fba_scraper_headless` | `False` | **keep False** — Amazon fingerprints headless |
| `fba_scraper_host_resolver_rules` | `""` | escape hatch for networks where Chromium DNS fails but the OS resolver works (see §8). Passed as `--host-resolver-rules`. **Leave blank in production.** |
| `fba_scraper_min/max_delay_seconds` | `1.0` / `10.0` | random sleep between orders |
| `fba_scraper_max_attempts_per_order` | `2` | give up a single buyer name after N page loads |

---

## 7. Seeding & refreshing the Chromium profile  ← **the runbook**

The scraper needs a logged-in Seller Central session in
`/data/fba-profile` (the `fba_profile` volume). You get it from the profile
`FBA/open_browser.py` uses — i.e. the directory named by
**`chrome_profile_path` in `FBA/config.json`** (currently
`/home/las/USAV/ZohoIntegration/FBA/data/chrome_profile`, *not*
`FBA/data/chrome_profile`). Amazon sessions last weeks but do expire.

> **Cookies only — never the whole profile.** A full-profile copy `SIGTRAP`-
> crashes Chromium on launch whenever the workstation's Chrome is a newer major
> version than the container's bundled Chromium (pinned by `playwright`). The
> login cookies are basic-store (`v10`) encrypted with a fixed key, so they
> port on their own. `Backend/misc/fba_seed_profile.sh` does exactly this.

### 7a. First-time seed (once)

```bash
# 1. Log in on a workstation (any Chrome version is fine now):
cd /home/las/USAV/FBA
python3 open_browser.py          # sign in, clear OTP/2FA, reach the dashboard, Ctrl+C

# 2. Seed the volume with just the cookies (run from the repo root):
cd ~/USAV_Inventory
Backend/misc/fba_seed_profile.sh \
    /home/las/USAV/ZohoIntegration/FBA/data/chrome_profile prod
#   (use 'dev' as the 2nd arg for the backend-dev container)

# 3. Verify
docker compose --profile prod exec -e PYTHONPATH=/app -w /app backend \
    python -u misc/fba_scrape_smoke.py
#    -> "check_auth -> logged_in"
```

The script wipes `/data/fba-profile`, copies `Default/Cookies` (+
`Default/Network/Cookies`, `Local Storage` if present), chowns to `appuser`,
and clears `Singleton*` locks.

**If the prod server is a different machine** (the deploy host has no logged-in
profile): log in on your workstation, then copy just the cookies over and seed
there:

```bash
# workstation → server
ssh deploy@server 'mkdir -p /tmp/fba-seed/Default'
scp /home/las/USAV/ZohoIntegration/FBA/data/chrome_profile/Default/Cookies \
    deploy@server:/tmp/fba-seed/Default/Cookies

# on the server
ssh deploy@server
cd ~/USAV_Inventory
Backend/misc/fba_seed_profile.sh /tmp/fba-seed prod && rm -rf /tmp/fba-seed
```

### 7b. When the session has expired

Symptoms:

* the import dialog's **"Check Seller Central login"** says *"Signed out —
  refresh the profile"* (a real credential form was rendered), or
* a job finishes **`completed_with_warnings`** with
  *"Amazon Seller Central session expired — orders were imported without buyer
  names"* and the per-order grid shows `AUTH_EXPIRED`.

*"Couldn't verify"* / `unverified` on its own is **not** proof of an expired
session — see §8 (the check couldn't load the page). Run an actual import; if the
per-order grid comes back `FOUND`/`NOT_FOUND` the session is fine.

The import still worked — orders are in, just without the freshly-scraped buyer
names. To restore name scraping:

```bash
# Same as 7a: re-login on a workstation, then re-run fba_seed_profile.sh.
cd /home/las/USAV/FBA && python3 open_browser.py    # sign in, Ctrl+C
cd ~/USAV_Inventory && Backend/misc/fba_seed_profile.sh \
    /home/las/USAV/ZohoIntegration/FBA/data/chrome_profile prod
```

> **Do not** try to log in *inside* the container — it is headless (Xvfb) with no
> way to type a password or pass 2FA. Always log in on a workstation.

### 7c. Notes

* The cookies copy is tiny (<1 MB) and instant.
* If the scraper reports *"Chromium failed to open the profile"* (`FbaScraper
  Unavailable`), someone copied a whole profile instead of running
  `fba_seed_profile.sh` — re-seed cookies-only.
* `fba_seed_profile.sh` clears `Singleton*` locks; Chromium leaves a
  `SingletonLock` symlink that otherwise blocks launch with *"Opening in
  existing browser session"*.
* Nothing else touches that volume, so re-seeding while no import runs is safe.

---

## 8. Operating & debugging

**Smoke test** — `Backend/misc/fba_scrape_smoke.py`:

```bash
# just check the profile is logged in:
docker compose --profile prod exec -e PYTHONPATH=/app -w /app backend \
    python -u misc/fba_scrape_smoke.py

# scrape specific orders:
docker compose --profile prod exec -e PYTHONPATH=/app -w /app backend \
    python -u misc/fba_scrape_smoke.py --order-id 112-1234567-1234567
```

**Logs** — `docker compose --profile prod logs -f backend | grep -i fba`.

**In the UI** — every phase, warning, and per-order `detail` is on the panel;
`job.last_error` shows on failure.

**Expected behaviours, not bugs:**

* `NOT_FOUND` for an order whose Seller Central page genuinely doesn't render a
  buyer-name link — the order still imports.
* `completed_with_warnings` with everything `AUTH_EXPIRED` — see §7b.
* Re-uploading yesterday's files today: `orders_created` is small/zero, most
  orders are silent in-place updates. That is the dedupe working.

**Occasionally seen: Chromium `ERR_NAME_NOT_RESOLVED` for external hosts** on
some VPN / Docker-Desktop DNS setups even though the OS resolver + `curl` work.
It is usually transient. If it persists, for a **local test only** set
`FBA_SCRAPER_HOST_RESOLVER_RULES="MAP *amazon.com <sellercentral-ip>"` — never in
production (it pins every host to one IP). Getting `unverified` from
`check_auth` while `curl https://sellercentral.amazon.com/` works from inside the
container points at this.

**"Signed out" when you think the profile is fine:** almost always the
`max_auth_age` re-auth described in §2 — Amazon wants the password re-entered
even though it still knows the account. Fix is the same as a real sign-out:
§7b.

---

## 9. Known limitations / future work

* **Multi-worker status flicker** (§3) — same as tracking. Move to an
  `fba_import_jobs` table if it matters.
* **No restart recovery** — re-upload (idempotent).
* **Headless login refresh** needs a workstation + manual copy (§7b). A VNC-into-
  `Xvfb` flow or a stored-2FA-secret automation could remove the copy step.
* **`get_input.py` auto-fetch is not ported** — the operator still downloads the
  two reports by hand. The dialog only *computes and shows* the right window.

---

## 10. File map

**Backend**
```
app/modules/fba/
  __init__.py
  pipeline.py     build_merged_rows, merge_rows, pick_period_days, rows_to_csv_text
  scraper.py      FbaBuyerNameScraper, _settle_sso (account picker), FbaAuthExpired,
                  FbaScraperUnavailable, BuyerNameScraperProtocol
  runner.py       job state, _process (parsing→scraping→ingesting), start_job, abort
  routes.py       /api/v1/fba/import/* endpoints
  schemas.py      Pydantic in/out models
app/modules/orders/import_ingest.py     ingest_parsed_rows + StaticImportClient
                                        (shared with the manual CSV import route)
app/core/config.py                      fba_* settings
app/main.py                             fba_router registration
Backend/Dockerfile                      mkdir/chown /data/fba-profile
Backend/misc/fba_scrape_smoke.py        manual smoke test (check_auth + --order-id)
Backend/misc/fba_seed_profile.sh        cookies-only profile seeder (§7)
tests/modules/fba/                      test_fba_pipeline.py (8), test_fba_runner.py (10),
                                        test_fba_routes.py (4)
```

**Frontend**
```
src/types/fba.ts,  src/api/fba.ts,  src/api/endpoints.ts (FBA)
src/context/FbaImportContext.tsx
src/components/fba/{FbaImportPanel,GlobalFbaImportChip,FbaImportResultChip}.tsx
src/components/orders/FbaOrderImportButton.tsx
src/components/orders/OrderImportButton.tsx     delegates to FbaOrderImportButton for FBA
src/main.tsx                                    <FbaImportProvider> + <FbaImportPanel/>
src/components/common/Layout.tsx                <GlobalFbaImportChip/>
```

**docker-compose.yml** — `fba_profile` named volume on `backend` + `backend-dev`.

**Tests:** `pytest Backend/tests/modules/fba` — 22 tests. Full backend suite: 132 passing.

**Verified locally (dev container):**
* pipeline output byte-identical to an archived `final_orders` CSV
* end-to-end runner → real dev DB: order created with the right
  channel/source/totals; re-import is idempotent (in-place update, no dupes)
* **live buyer-name scrape** against real Seller Central orders after a
  cookies-only seed — `check_auth -> logged_in`, names pulled via
  `[data-test-id="buyer-name-with-link"]` (e.g. `702-1973617-9964255 → "Alejandro"`)
