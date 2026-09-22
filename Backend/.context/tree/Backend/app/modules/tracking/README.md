# Backend\app\modules\tracking

## What This Folder Does
Server-side, manually-triggered scraping of parcelsapp.com to refresh the
`shipping_status` of eligible sales orders. Replaces the local
`scrape_tracking.py` + `SHIPPING_STATUS_CSV` upload round-trip.

- `scraper.py` — **headed** Chromium (inside `Xvfb` via `pyvirtualdisplay`) +
  `playwright-stealth`. Intercepts the `/api/v2/parcels` JSON response and
  classifies from that (DOM fallback if the API shape changes). `ScraperProtocol`
  is the test seam; `classify_api()` / `_classify_dom()` are pure and unit-tested.
- `runner.py` — single-job orchestrator held in module-level state (same pattern
  as the Zoho bulk-sync job in `app/modules/inventory/routes/zoho.py`). Owns the
  queue, rate-limit pause, probe-gated resume, and auto-probe loop.
- `status_mapping.py` — `map_scraped_status()`, shared with the
  `SHIPPING_STATUS_CSV` import in `app/modules/orders/routes.py`.
- `routes.py` — `/api/v1/tracking/*` endpoints (ADMIN or SALES_REP).

## Common Pitfalls
- **One job at a time, in-memory.** State lives in module globals in the worker
  process that received `POST /tracking/sync/start`. With multiple uvicorn
  workers (`--workers` in the Dockerfile), `GET /tracking/sync/status` may hit a
  worker that does not hold the job — same limitation as the existing Zoho bulk
  sync. Per-order results are still committed to the DB as they land.
- **Restart = re-click.** A backend restart drops the in-memory job. There is no
  recovery code by design: `orders.tracking_last_checked_at` + the
  `tracking_freshness_hours` guard mean re-running the job simply skips
  already-checked orders.
- **Must run headed.** parcelsapp's anti-bot returns `{"error":"RELOAD"}` to
  headless / automated browsers and never yields data (this is what produced
  "status unknown"). `tracking_scraper_headless` defaults to **False**; the
  container needs `Xvfb` + `xauth` (Dockerfile) and `pyvirtualdisplay`.
- **Rate limit ≠ failure.** `{"error":"RELOAD"}` (anti-bot) maps to
  `RATE_LIMITED`; `{"error":"NO_DATA"}` maps to `NOT_FOUND`. The job only pauses
  after `tracking_rate_limit_threshold` (default 3) *consecutive* RELOADs.
- **Carrier event text has non-breaking spaces** (` `, esp. FedEx) —
  `classify_api` normalises whitespace before keyword matching. "Label created" /
  "order created" as the only event ⇒ `PENDING` even when parcelsapp's top-level
  `status` is optimistically `transit`.
- **Debug:** `misc/tracking_scrape_smoke.py` runs the real scraper against real
  orders (or `--tn <number>`) and prints per-order status + `detail`. Job logs at
  INFO: `tracking job=… [n/N] <tn> → <STATUS> (<detail>)`. `job.last_error` and
  each item's `detail` are exposed in the API/UI.
- **Resume is probe-gated, not timer-gated.** `cooldown_until` is advisory only.
  `POST /tracking/sync/resume` returns 409 unless the last probe returned `OK`.
- **Deps.** `playwright==1.55.0` + `playwright-stealth==2.0.0` +
  `pyvirtualdisplay==3.0` in `requirements.txt`. In the Dockerfile: the **builder**
  stage runs `playwright install chromium` (browser binary, cached with the pip
  layer — only re-downloads when `requirements.txt` changes); the **runtime**
  stage `COPY`s `/opt/pw-browsers` from the builder and runs
  `playwright install-deps chromium` for the shared libs, plus `xvfb`/`xauth`.
  Keep the `playwright` pin — Playwright refuses to run a mismatched browser
  build. If any piece is missing the job ends `failed` — it does not crash the app.
- **Browser profiles vs binaries.** `PLAYWRIGHT_BROWSERS_PATH` holds versioned
  browser binaries only — safe to reinstall/COPY, never contains logins. A future
  integration needing a persistent session (Amazon FBA) must pass its own mounted
  `user_data_dir` to `launch_persistent_context`, isolated from this scraper and
  out of the image.
- **Server IP reputation.** Verified working from the dev host at ~12 lookups with
  no throttling. The "~55 then cooldown" ceiling still needs a longer run to
  confirm server-side. Tunables live in `app/core/config.py` (`tracking_*`).
- **DIRTY side effect.** Persisting `DELIVERED`/`SHIPPING` sets
  `zoho_sync_status = DIRTY`, so a large run queues many Zoho outbound syncs.

## Child Folders
- (none)
