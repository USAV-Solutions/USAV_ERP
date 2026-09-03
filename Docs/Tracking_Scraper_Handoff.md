# Tracking Status Scraper — Handoff

## Overview

The `tracking` module (`Backend/app/modules/tracking/`) is a manually-triggered,
server-side background job that checks the delivery status of pending sales
orders against **parcelsapp.com** and writes the result back to
`orders.shipping_status`. It replaces the old workflow of running
`tracking-check/scrape_tracking.py` on a laptop and uploading the resulting CSV
through the `SHIPPING_STATUS_CSV` import.

It is driven by a **"Check Tracking" button** on the Orders page (self-fulfilled
view). The job runs on the server, so the user can navigate away; a navbar chip
and a slide-out monitor panel show progress and let them reopen it anywhere.

parcelsapp has no usable public API and actively blocks bots, so the scraper
drives a **real (headed) Chromium browser** via Playwright, inside a virtual X
display. This document is about how that browser automation piece works and how
it is wired into the rest of the app.

---

## 1. Why Playwright, and why headed

parcelsapp renders **nothing** server-side. The tracking page loads a JS bundle
that POSTs to `https://parcelsapp.com/api/v2/parcels` and builds the result from
that JSON response.

Their anti-bot layer fingerprints the browser (WebGL renderer, a deliberately
thrown JS error stack, etc.) and, for a **headless** or obviously-automated
browser, the API responds with `{"error":"RELOAD"}` (or an empty `200`) forever —
no data is ever returned. An earlier headless version of this scraper therefore
produced `UNKNOWN` on every single order.

What works, verified against real orders from the deploy host:

| Ingredient | Why |
| :--- | :--- |
| **Headed** Chromium (`headless=False`) | Headless is fingerprinted and blocked. |
| **`Xvfb` virtual display** (`pyvirtualdisplay`) | A headed browser needs an X server; the container has no real display. |
| **`playwright-stealth`** | Masks `navigator.webdriver` and other automation tells. |
| `--disable-blink-features=AutomationControlled` launch arg | Same purpose. |
| Reading the **`/api/v2/parcels` JSON** (not the DOM) | Robust, structured; DOM is a fallback only. |

There is a genuine rate limit: after roughly **50–55 lookups** from one IP in a
window, parcelsapp starts returning `RELOAD` / empty `200`s for an unknown
cooldown period. The whole "pause + probe + resume" design exists to handle this.

---

## 2. The scraper — `scraper.py`

### `TrackingScraper`

An async context manager that owns **one** virtual display + Chromium browser +
page for the lifetime of a job (not one per order):

```python
async with TrackingScraper(headless=settings.tracking_scraper_headless) as scraper:
    result = await scraper.scrape(tracking_number)   # -> ScrapeResult(status, detail)
```

* `start()` — starts `Xvfb` (if not headless), launches Chromium, opens a page,
  applies stealth. If `pyvirtualdisplay` or `Xvfb` is missing it logs a warning
  and falls back to headless (which will then be blocked → the job ends
  `failed`, it does not crash the app).
* `close()` — best-effort teardown of context, browser, Playwright, display.
* The browser **context is ephemeral** (`browser.new_context()`) — parcelsapp
  needs no login, nothing persists. A future integration that needs a persistent
  session (e.g. Amazon FBA login) must use `launch_persistent_context(user_data_dir=…)`
  pointed at its **own mounted volume**, never a path under
  `PLAYWRIGHT_BROWSERS_PATH` and never baked into the image.

### `scrape(tracking_number)` flow

1. Short-circuits: empty → `UNKNOWN`; starts with `TBA` → `SKIPPED_TBA`.
2. Attaches a `page.on("response", …)` listener that watches for
   `/api/v2/parcels` responses and buckets them:
   * valid JSON with real data → `payloads`
   * `{"error":"RELOAD"}`, empty body, or non-JSON `200` → `blocked` counter
     (all three are throttle signals)
3. `page.goto(parcelsapp_url, wait_until="domcontentloaded", timeout=25s)`.
4. Polls up to **30s** for a usable payload, but **bails after 12s** once it has
   seen throttle responses (parcelsapp's JS retries internally within ~10s, so
   waiting longer is pointless).
5. Resolution order:
   * got a payload → `classify_api(payload)`
   * only throttle responses → `RATE_LIMITED` (`detail`: "throttled (N empty/RELOAD…)")
   * nothing from the API → **DOM fallback**: read `.event-content strong`; if it
     contains "information has not been found yet" → `RATE_LIMITED`, "not found"
     → `NOT_FOUND`, otherwise classify from the event text; if even that fails →
     `UNKNOWN`
6. Any exception → `ERROR` with the message in `detail`.

### `classify_api(body)` — the mapping

parcelsapp's JSON has a top-level `status` code and a `states[]` array (newest
first). Classification uses both:

| Signal | Result |
| :--- | :--- |
| `{"error":"RELOAD"}` | `RATE_LIMITED` |
| `{"error":"NO_DATA"}` (or any other error) | `NOT_FOUND` |
| latest event text contains "delivered" (and not "not delivered" / "no authorized recipient" / …) | `DELIVERED` |
| top-level `status == "delivered"` | `DELIVERED` |
| `status == "archive"` | `DELIVERED` if latest event mentions delivery, else `SHIPPING` |
| latest event is label-only ("label created", "order created", "shipment information", …) | `PENDING` — *even if `status` optimistically says `transit`* |
| `status` in {`transit`, `pickup`, `expired`, `undelivered`, `alert`, `exception`} | `SHIPPING` |
| `status` in {`pending`, `""`} with no events | `NOT_FOUND` ("no tracking events yet") |
| `status == "notfound"` | `NOT_FOUND` |
| anything else with data present | `SHIPPING` (assume moving) |

Carrier event strings contain **non-breaking spaces** (FedEx especially), so
`latest` is whitespace-normalised (`re.sub(r"\s+", " ", …)`) before keyword
matching.

`classify_api` and `_classify_dom` are pure functions and are unit-tested
(`tests/modules/tracking/test_tracking_runner.py::test_classify_api` /
`test_classify_dom_fallback`).

### Result vocabulary

`DELIVERED`, `SHIPPING`, `PENDING`, `NOT_FOUND`, `UNKNOWN`, `ERROR`,
`RATE_LIMITED`, `SKIPPED_TBA`. Only `PERSISTABLE = {DELIVERED, SHIPPING, PENDING}`
are written to the DB; the rest are recorded on the job for the UI only and the
order is retried on the next run.

---

## 3. Orchestration — `runner.py`

### Job state

One job at a time, held in **module-level globals** in the worker process that
started it — the same pattern as the existing Zoho bulk-sync job
(`app/modules/inventory/routes/zoho.py`):

```python
_JOB_LOCK: asyncio.Lock
_CURRENT_JOB: TrackingJobState | None      # running OR paused
_LAST_JOB:    TrackingJobState | None      # most recent finished job
_CURRENT_TASK: asyncio.Task | None         # the _process() or _auto_probe_loop() task
_scraper_factory = TrackingScraper         # test seam (set_scraper_factory)
```

`TrackingJobState` holds `status`, the full `items` list (`TrackingItemState` per
tracking number, with `result`, `detail`, `checked_at`, `attempts`), `cursor`,
`counts`, `cooldown_until`, `consecutive_rate_limited`, `auto_probe`,
`last_probe_result`, `cancel_requested`, `message`, `last_error`.

Statuses: `running` → `paused_rate_limit` → `running` (loop), and terminal
`completed` / `aborted` / `failed`.

### Eligible-order query (`_eligible_where`)

```
shipping_status = PENDING
AND source        != 'AMAZON_FBA_CSV'
AND fulfillment_channel != AMAZON_FBA
AND tracking_number present, non-blank, not starting 'TBA'
AND (tracking_last_checked_at IS NULL OR < now() - tracking_freshness_hours)
```

Rows are grouped by tracking number (one `TrackingItemState` can map to several
`order_ids`, e.g. same number across platforms). The freshness cutoff makes a
re-run after a crash/redeploy idempotent — already-checked orders are skipped.

### The loop (`_process`)

For each item, in order:

1. If `attempts >= 4` → give up on it (mark `ERROR`, advance) so one bad number
   can't wedge the queue.
2. `scraper.scrape()` wrapped in `asyncio.wait_for(timeout=80s)`.
3. Log at INFO: `tracking job=<id> [n/N] <tracking_number> → <STATUS> (<detail>)`.
4. `RATE_LIMITED` → increment `consecutive_rate_limited`; at **3 consecutive**
   → `_enter_cooldown()` and return. A lone hit backs off and retries the same
   item (a fresh label parcelsapp hasn't ingested yet looks the same as a
   throttle).
5. Otherwise → `consecutive_rate_limited = 0`, `_apply_result()`, advance.
6. Sleep `random.uniform(2, 5)s` between items.
7. `CancelledError` → clean `aborted`; any other exception → `failed` with
   `last_error`.

### Persistence (`_apply_result`)

Only for `DELIVERED` / `SHIPPING` / `PENDING`. In its **own DB transaction** per
item (so progress survives a crash):

```python
for order in orders_with_this_tracking_number:
    order.tracking_last_checked_at = now
    if mapped_status and order.shipping_status != mapped_status:
        order.shipping_status = mapped_status
        order.zoho_sync_status = ZohoSyncStatus.DIRTY   # ← queues a Zoho outbound sync
```

The scraped-status → `ShippingStatus` mapping is `status_mapping.map_scraped_status`,
**shared with** the `SHIPPING_STATUS_CSV` file import in
`app/modules/orders/routes.py` (one source of truth). `PENDING` maps to `None`
(no status change) — it only stamps `tracking_last_checked_at`.

> **Side effect to be aware of:** a large run marks many orders `DIRTY`, which
> queues that many Zoho outbound syncs.

### Rate-limit handling

* `_enter_cooldown` — `status = paused_rate_limit`, browser closed,
  `cooldown_until = now + tracking_cooldown_minutes` (**advisory only**).
* `probe()` — scrapes exactly **one** remaining item with a fresh short-lived
  scraper. Success → `last_probe_result = "OK"`, that item is persisted. Still
  blocked → stays paused; a probe that stays `RATE_LIMITED` for `attempts >= 4`
  on the same item skips it so it can't wedge the probe forever.
* `resume()` — 409 unless `last_probe_result == "OK"`; then spawns `_process`
  from the current cursor.
* `auto_probe` (default **on**) — while paused, `_auto_probe_loop` probes every
  `tracking_auto_probe_interval_minutes` (15), doubling up to
  `tracking_auto_probe_max_interval_minutes` (90) on repeated failure, and
  auto-resumes on the first clear probe. Toggled via `PATCH /sync/auto-probe`.

### Abort

`abort()` sets `cancel_requested`, cancels `_CURRENT_TASK` (interrupting an
in-flight scrape or a cooldown wait), and for a running job `await`s the task so
it returns `aborted` in ~0.1s. Committed progress stays; the rest is picked up
next run.

### Multi-worker caveat

Production runs `uvicorn --workers 4`. The job lives in **one** worker's memory,
so `GET /tracking/sync/status` can occasionally hit a different worker and show
"idle" briefly. The job itself is unaffected. Same limitation as the existing
Zoho bulk sync. Fix if it becomes a problem: `--workers 1`, or move job state to
a `tracking_jobs` table.

A backend restart drops the in-memory job entirely — there is **no** restart
recovery by design. The `tracking_last_checked_at` freshness guard means
re-clicking "Check Tracking" just skips what was already done.

### Final step — push to Zoho

`_apply_result` records, per item, `changed_order_ids` — the subset of that
item's orders whose `shipping_status` actually flipped (i.e. got marked `DIRTY`).
`TrackingJobState.changed_order_ids` (and the schema field) is the flattened,
de-duped list. The frontend uses it to offer a "Sync to Zoho" step once the job
stops — see §5. Nothing on the backend pushes to Zoho automatically; the DIRTY
flag alone just makes the orders eligible for the next Range Sync.

---

## 4. API — `routes.py`

Prefix `/api/v1/tracking`. All endpoints require **ADMIN or SALES_REP**
(`AdminOrSalesUser`), matching the `SHIPPING_STATUS_CSV` import this replaces.

| Method & path | Purpose |
| :--- | :--- |
| `GET  /eligible` | `{count}` for the button badge |
| `POST /sync/start` | Start a job (202; 409 if one is active) |
| `GET  /sync/status` | Poll — full `TrackingJobOut` (`{status:"idle"}` if none) |
| `POST /sync/probe` | Scrape one order to test the block; `{result, job}` |
| `POST /sync/resume` | Resume after a cleared probe (202; 409 otherwise) |
| `POST /sync/abort` | Stop the job |
| `PATCH /sync/auto-probe` | `{enabled: bool}` |

Router registered in `app/main.py` next to the other module routers.

---

## 5. Frontend integration

React + MUI + react-query. All under `frontend/src/`.

| File | Role |
| :--- | :--- |
| `types/tracking.ts` | Mirrors `schemas.py` |
| `api/tracking.ts`, `api/endpoints.ts` (`TRACKING`) | axios wrappers |
| `context/TrackingSyncContext.tsx` | **Single source of truth.** One polling `useQuery(['trackingJob'])` (2.5s while a job is active or the panel is open, off otherwise) + panel open/close state + start/probe/resume/abort/auto-probe mutations. Gated on `hasRole(['ADMIN','SALES_REP'])`. Provider mounted in `main.tsx` inside `AuthProvider`. |
| `hooks/useTrackingEligibleCount.ts` | On-demand `GET /eligible` (30s stale) for the button badge |
| `components/tracking/TrackingSyncButton.tsx` | Toolbar button, rendered in `OrdersManagement.tsx` next to `<OrderImportButton>` (self-fulfilled view only). "Check Tracking (N)" idle → confirm dialog → start + open panel. "Tracking n/m" / "Tracking paused" while active → open panel. |
| `components/tracking/TrackingSyncPanel.tsx` | Right-side drawer. Progress bar, count chips, `job.message`, `job.last_error` alert, the cooldown banner, a `DataGrid` queue (order #, tracking link → parcelsapp, result chip, `detail`, checked-at), Abort (confirm) / Close. Mounted once in `main.tsx`. |
| `components/tracking/TrackingCooldownBanner.tsx` | Shown while paused. Advisory countdown, "Probe 1 order", "Resume (N)" (disabled until `last_probe_result === "OK"`), auto-probe toggle. |
| `components/tracking/TrackingZohoSyncStep.tsx` | **Final step.** Shown in the panel once the job stops, if `job.changed_order_ids` is non-empty. "Sync N fulfillment updates to Zoho" → `useOrderZohoSync(changed_order_ids)` → queue + poll + progress. |
| `hooks/useOrderZohoSync.ts` | Reusable: takes order ids → `forceSyncOrder` each → poll `getOrderSyncStatuses` to completion. Extracted from the Orders page "Range Sync" queue/poll loop (which is not yet refactored to use it). |
| `components/tracking/TrackingResultChip.tsx` | Reusable status chip (mirrors `ZohoSyncStatusChip`) |
| `components/tracking/GlobalTrackingChip.tsx` | Navbar chip in `Layout.tsx` — shows while a job runs / paused / just-finished (5-min window); click reopens the panel from any route |

The button and the navbar chip both just open the one shared `<TrackingSyncPanel>`.

---

## 6. Database

**Migration `0041`** (`Revises: 0040`) adds one column:

```
orders.tracking_last_checked_at  TIMESTAMPTZ NULL   + ix_orders_tracking_last_checked_at
```

That is the only schema change. Status results go to the **existing**
`orders.shipping_status` (+ `zoho_sync_status = DIRTY`), reusing the mapping the
CSV import already used. No new tables.

---

## 7. Configuration (`app/core/config.py`)

All optional, sane defaults; override via the `backend` service `environment:`
block in `docker-compose.yml` (prod has no `.env` file).

| Setting | Default | Notes |
| :--- | :--- | :--- |
| `tracking_scraper_headless` | `False` | **Keep False.** True only for local debugging with a real display. |
| `tracking_scraper_min/max_delay_seconds` | `2.0` / `5.0` | Random sleep between orders |
| `tracking_rate_limit_threshold` | `3` | Consecutive `RATE_LIMITED` hits before pausing |
| `tracking_cooldown_minutes` | `30` | Advisory countdown only |
| `tracking_auto_probe_interval_minutes` | `15` | Auto-probe cadence while paused |
| `tracking_auto_probe_max_interval_minutes` | `90` | Backoff ceiling |
| `tracking_freshness_hours` | `6` | Orders checked more recently are skipped when (re)building the queue |

---

## 8. Deployment — Dockerfile (`Backend/Dockerfile`)

Two-stage build, structured so the ~170 MB Chromium download is **cached** and
only re-runs when `requirements.txt` changes (i.e. when the `playwright` pin is
bumped) — not on code changes.

**Builder stage** (after `pip install -r requirements.txt`):
```dockerfile
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers
RUN playwright install chromium          # browser binary only, cached with the pip layer
```

**Runtime stage:**
```dockerfile
# apt line adds: xvfb  xauth
COPY --from=builder /opt/pw-browsers /opt/pw-browsers   # browser, no re-download
RUN playwright install-deps chromium \                   # shared libs only (fast, cached)
    && rm -rf /var/lib/apt/lists/* \
    && chmod -R a+rX /opt/pw-browsers                     # readable by non-root appuser
ENV HOME=/home/appuser                                    # ← headed Chrome needs this
```

> **`ENV HOME=/home/appuser` is load-bearing.** The `python:3.12-slim` base bakes
> `HOME=/root`, which the non-root `appuser` can't write. Headed Chrome puts its
> crashpad database under `$HOME/.config/chromium/` — if that can't be created
> the crashpad handler rejects its args and **Chrome `SIGTRAP`s on launch**
> (`chrome_crashpad_handler: --database is required` → `Trace/breakpoint trap`).
> `chrome-headless-shell` (Playwright's headless binary) has no crashpad, so
> *headless* was unaffected — which made this look like a headed-only / host
> problem. `scraper.py` also passes `env=_browser_env()` (a writable `HOME`
> fallback) as belt-and-braces. First seen on an LXC deploy host (`ct103`); it's
> not LXC-specific — any non-root container without a writable `HOME` hits it.

**Python deps** (`requirements.txt`): `playwright==1.55.0`,
`playwright-stealth==2.0.0`, `pyvirtualdisplay==3.0`.

> Keep `playwright` pinned — Playwright refuses to run a browser build it wasn't
> compiled for, and the browser comes from the cached builder layer.

`docker-compose.yml` needs no changes — both `backend` (prod) and `backend-dev`
build from this Dockerfile. Deploy (`.github/workflows/deploy.yml`) runs
`alembic upgrade head` and `docker compose up -d --build` automatically on push
to `main`; the first build after this lands is slow, subsequent ones are normal.

**Verified:** on the `ct103` LXC deploy host, headed Chromium launches in Xvfb
and parcelsapp returns real data (`SHIPPING` / `DELIVERED` with event text) —
but **only after `ENV HOME=/home/appuser`**. Before that, headed Chrome
`SIGTRAP`'d and every lookup came back `NO_DATA` headless (parcelsapp soft-block).

---

## 9. Operating & debugging

**Smoke script** — `Backend/misc/tracking_scrape_smoke.py`:
```bash
# real orders from the DB:
docker compose --profile prod exec -e PYTHONPATH=/app -w /app backend \
    python misc/tracking_scrape_smoke.py 5

# a specific number, no DB:
docker compose --profile prod exec -e PYTHONPATH=/app -w /app backend \
    python misc/tracking_scrape_smoke.py --tn 9400100000000000000000
```

**Logs** — `docker compose --profile prod logs -f backend | grep tracking`
(one INFO line per order).

**In the UI** — every queue row shows a `detail` string; `job.last_error` and
`job.message` are shown in the panel.

**Expected behaviors, not bugs:**
* First lookups after a burst of testing return `RATE_LIMITED` — the ~55/window
  ceiling. Wait ~30–60 min or use the probe button.
* `PENDING` for an order whose only carrier event is "label created" / "order
  created", even though it has a tracking number.
* The job pausing itself after 3 consecutive `RATE_LIMITED`.

---

## 10. Known limitations / possible future work

* **Multi-worker status flicker** (§3). Move to a `tracking_jobs` table if it
  matters.
* **No restart recovery** — re-click the button (freshness guard handles it).
* **Rate-limit ceiling unquantified server-side** — short runs are clean; a full
  ~200-order run from the deploy IP hasn't been measured end to end. If it
  becomes painful, options are a residential proxy or the paid ParcelsApp API
  (which would remove the whole browser + cooldown machinery).
* **`playwright install` in a named volume** instead of an image layer would
  drop even the requirements-triggered re-download, at the cost of a compose
  volume + an idempotent entrypoint check. Not done.

---

## 11. File map

**Backend**
```
app/modules/tracking/
  scraper.py          TrackingScraper, classify_api, _classify_dom, ScraperProtocol
  runner.py           job state, _process loop, probe/resume/abort, eligible query
  routes.py           /api/v1/tracking/* endpoints
  schemas.py          Pydantic in/out models
  status_mapping.py   map_scraped_status (shared with orders CSV import)
app/core/config.py                         tracking_* settings
app/main.py                                router registration
app/modules/orders/models.py               Order.tracking_last_checked_at
app/modules/orders/routes.py               SHIPPING_STATUS_CSV import now uses map_scraped_status
migrations/versions/…_0041_add_order_tracking_last_checked_at.py
misc/tracking_scrape_smoke.py              manual debug tool
tests/modules/tracking/                    test_tracking_runner.py, test_tracking_routes.py
Backend/Dockerfile                         builder-cached chromium + xvfb/xauth
Backend/requirements.txt                   playwright, playwright-stealth, pyvirtualdisplay
Backend/.context/tree/Backend/app/modules/tracking/README.md
```

**Frontend**
```
src/types/tracking.ts
src/api/tracking.ts,  src/api/endpoints.ts (TRACKING)
src/context/TrackingSyncContext.tsx
src/hooks/useTrackingEligibleCount.ts
src/hooks/useOrderZohoSync.ts              reusable queue-and-poll for outbound Zoho sync
src/components/tracking/{TrackingSyncButton,TrackingSyncPanel,TrackingCooldownBanner,TrackingResultChip,GlobalTrackingChip,TrackingZohoSyncStep}.tsx
src/main.tsx                               <TrackingSyncProvider> + <TrackingSyncPanel/>
src/components/common/Layout.tsx           <GlobalTrackingChip/>
src/pages/OrdersManagement.tsx             <TrackingSyncButton/>
```

**Tests:** `pytest Backend/tests/modules/tracking` — 14 tests (classification,
queue, rate-limit pause, probe-gated resume, abort, route 409s). Full backend
suite: 110 passing.
