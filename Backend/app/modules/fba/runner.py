"""
FBA import job orchestrator.

One job at a time, held in module-level state (same pattern as the tracking
scraper in ``app/modules/tracking/runner.py`` and the Zoho bulk-sync job). The
job runs as a single ``asyncio`` task:

    parsing → scraping (buyer names) → ingesting → completed
                                                 ↘ completed_with_warnings
                                                 ↘ aborted / failed

Buyer-name scraping is best-effort: a missing name never blocks the import, and
if the Chromium profile's Seller Central session has expired the job finishes
``completed_with_warnings`` with the orders imported (without names) and a
message pointing at ``Docs/FBA_Import_Handoff.md``.
"""
from __future__ import annotations

import asyncio
import logging
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.core.config import settings
from app.core.database import async_session_factory
from app.modules.fba.pipeline import (
    PipelineError,
    build_merged_rows,
    rows_to_csv_text,
)
from app.modules.fba.scraper import (
    AUTH_SIGNED_OUT,
    BuyerNameScraperProtocol,
    FbaAuthExpired,
    FbaBuyerNameScraper,
    FbaScraperUnavailable,
)

logger = logging.getLogger(__name__)

# ── Job statuses / phases ───────────────────────────────────────────────────
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_COMPLETED_WARN = "completed_with_warnings"
STATUS_ABORTED = "aborted"
STATUS_FAILED = "failed"
_TERMINAL = {STATUS_COMPLETED, STATUS_COMPLETED_WARN, STATUS_ABORTED, STATUS_FAILED}

PHASE_PARSING = "parsing"
PHASE_SCRAPING = "scraping"
PHASE_INGESTING = "ingesting"
PHASE_DONE = "done"

_HANDOFF_DOC = "Docs/FBA_Import_Handoff.md"

# Scrape-result buckets for the per-order grid.
R_FOUND = "FOUND"
R_NOT_FOUND = "NOT_FOUND"
R_ERROR = "ERROR"
R_SKIPPED = "SKIPPED"
R_AUTH_EXPIRED = "AUTH_EXPIRED"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class JobAlreadyRunning(RuntimeError):
    pass


class NoActiveJob(RuntimeError):
    pass


# ── State ────────────────────────────────────────────────────────────────────
@dataclass
class BuyerNameItemState:
    order_id: str
    result: str | None = None
    buyer_name: str | None = None
    detail: str | None = None
    attempts: int = 0
    checked_at: datetime | None = None


@dataclass
class FbaImportJobState:
    job_id: str
    status: str = STATUS_RUNNING
    phase: str = PHASE_PARSING
    started_at: datetime = field(default_factory=_utcnow)
    finished_at: datetime | None = None
    triggered_by: str | None = None

    # pipeline stats
    all_order_rows: int = 0
    fba_order_rows: int = 0
    shipment_rows: int = 0
    merged_rows: int = 0

    items: list[BuyerNameItemState] = field(default_factory=list)  # buyer-name targets
    scrape_cursor: int = 0
    counts: dict[str, int] = field(default_factory=dict)

    # ingestion result
    orders_created: int = 0
    orders_updated: int = 0
    items_created: int = 0

    warnings: list[str] = field(default_factory=list)
    message: str | None = None
    last_error: str | None = None
    cancel_requested: bool = False

    @property
    def total_names(self) -> int:
        return len(self.items)

    @property
    def scraped_names(self) -> int:
        return sum(1 for it in self.items if it.result is not None)


# Module-level singletons.
_JOB_LOCK = asyncio.Lock()
_CURRENT_JOB: FbaImportJobState | None = None
_LAST_JOB: FbaImportJobState | None = None
_CURRENT_TASK: asyncio.Task | None = None

# Test seam — overridden with a fake that yields scripted buyer names.
_scraper_factory = FbaBuyerNameScraper


def set_scraper_factory(factory) -> None:
    global _scraper_factory
    _scraper_factory = factory


def _is_active(job: FbaImportJobState | None) -> bool:
    return job is not None and job.status == STATUS_RUNNING


def get_state() -> FbaImportJobState | None:
    return _CURRENT_JOB or _LAST_JOB


def _count(job: FbaImportJobState, bucket: str) -> None:
    job.counts[bucket] = job.counts.get(bucket, 0) + 1


def _build_service(session):
    from app.repositories.inventory import PlatformListingRepository
    from app.repositories.orders.order_repository import (
        OrderItemRepository,
        OrderRepository,
    )
    from app.repositories.orders.sync_repository import SyncRepository
    from app.modules.orders.service import OrderSyncService

    return OrderSyncService(
        session=session,
        sync_repo=SyncRepository(session),
        order_repo=OrderRepository(session),
        order_item_repo=OrderItemRepository(session),
        listing_repo=PlatformListingRepository(session),
    )


# ── Core ────────────────────────────────────────────────────────────────────
async def _scrape_buyer_names(job: FbaImportJobState, rows: list[dict]) -> None:
    """Fill missing buyer-name on ``rows`` in place. Best-effort."""
    if not job.items:
        return

    profile_path = settings.fba_chrome_profile_path
    if not profile_path:
        job.warnings.append("Buyer-name scraping skipped: fba_chrome_profile_path not set.")
        for it in job.items:
            it.result = R_SKIPPED
            _count(job, R_SKIPPED)
        return

    rows_by_order: dict[str, list[dict]] = {}
    for row in rows:
        rows_by_order.setdefault(row.get("order-id", ""), []).append(row)

    min_delay = settings.fba_scraper_min_delay_seconds
    max_delay = settings.fba_scraper_max_delay_seconds
    max_attempts = settings.fba_scraper_max_attempts_per_order

    scraper: BuyerNameScraperProtocol = _scraper_factory(
        profile_path=profile_path,
        headless=settings.fba_scraper_headless,
        host_resolver_rules=settings.fba_scraper_host_resolver_rules,
    )
    try:
        await scraper.start()
        auth = await scraper.check_auth()
        if auth == AUTH_SIGNED_OUT:
            raise FbaAuthExpired("Seller Central profile is signed out")
        # AUTH_UNVERIFIED (page wouldn't load): try scraping anyway — the first
        # order load will raise FbaAuthExpired for real if the session is dead.

        while job.scrape_cursor < len(job.items):
            if job.cancel_requested:
                return
            item = job.items[job.scrape_cursor]
            item.attempts += 1
            try:
                res = await asyncio.wait_for(
                    scraper.scrape_buyer_name(item.order_id), timeout=90
                )
            except FbaAuthExpired:
                raise
            except asyncio.TimeoutError:
                res = None
                item.detail = "timed out"
            except Exception as exc:  # noqa: BLE001
                res = None
                item.detail = str(exc)[:160]

            if res is not None and res.buyer_name:
                item.buyer_name = res.buyer_name
                item.detail = res.detail
                item.result = R_FOUND
                for row in rows_by_order.get(item.order_id, []):
                    if not row.get("buyer-name"):
                        row["buyer-name"] = res.buyer_name
                _count(job, R_FOUND)
            elif item.attempts < max_attempts and not job.cancel_requested:
                # retry same item
                await asyncio.sleep(random.uniform(min_delay, max_delay))
                continue
            else:
                item.result = R_NOT_FOUND if res is not None else R_ERROR
                if item.result == R_ERROR:
                    job.last_error = f"{item.order_id}: {item.detail}"
                _count(job, item.result)

            item.checked_at = _utcnow()
            job.scrape_cursor += 1
            await asyncio.sleep(random.uniform(min_delay, max_delay))
    except FbaAuthExpired as exc:
        logger.warning("FBA import job %s: Seller Central session expired (%s)", job.job_id, exc)
        job.warnings.append(
            "Amazon Seller Central session expired — orders were imported without "
            f"buyer names. Refresh the Chromium profile: see {_HANDOFF_DOC}."
        )
        for it in job.items:
            if it.result is None:
                it.result = R_AUTH_EXPIRED
                _count(job, R_AUTH_EXPIRED)
    except FbaScraperUnavailable as exc:
        logger.warning("FBA import job %s: scraper unavailable (%s)", job.job_id, exc)
        job.warnings.append(f"Buyer-name scraping unavailable: {exc}")
        for it in job.items:
            if it.result is None:
                it.result = R_SKIPPED
                _count(job, R_SKIPPED)
    finally:
        try:
            await scraper.close()
        except Exception:  # noqa: BLE001
            pass


async def _process(job: FbaImportJobState, all_orders_txt: str, fulfillment_csv: str) -> None:
    global _CURRENT_JOB, _LAST_JOB, _CURRENT_TASK
    try:
        # ── 1. parse + merge ───────────────────────────────────────────────
        job.phase = PHASE_PARSING
        job.message = "Merging All-Orders and Fulfilment reports…"
        fieldnames, rows, stats = build_merged_rows(all_orders_txt, fulfillment_csv)
        job.all_order_rows = stats.all_order_rows
        job.fba_order_rows = stats.fba_order_rows
        job.shipment_rows = stats.shipment_rows
        job.merged_rows = stats.merged_rows
        job.warnings.extend(stats.warnings)

        seen_orders: set[str] = set()
        for row in rows:
            oid = row.get("order-id", "")
            if oid and not row.get("buyer-name") and oid not in seen_orders:
                seen_orders.add(oid)
                job.items.append(BuyerNameItemState(order_id=oid))

        if job.cancel_requested:
            raise asyncio.CancelledError

        # ── 2. scrape missing buyer names ─────────────────────────────────
        if rows:
            job.phase = PHASE_SCRAPING
            job.message = (
                f"Looking up {job.total_names} missing buyer name(s)…"
                if job.items
                else "No buyer names missing — skipping scrape."
            )
            await _scrape_buyer_names(job, rows)

        if job.cancel_requested:
            raise asyncio.CancelledError

        # ── 3. ingest ────────────────────────────────────────────────────
        job.phase = PHASE_INGESTING
        job.message = "Importing orders…"
        if rows:
            from app.modules.orders.routes import _parse_amazon_fba_csv
            from app.modules.orders.import_ingest import ingest_parsed_rows
            from app.modules.orders.models import OrderFulfillmentChannel

            csv_text = rows_to_csv_text(fieldnames, rows)
            parsed_rows, _seen, _skipped = _parse_amazon_fba_csv(csv_text)
            async with async_session_factory() as session:
                service = _build_service(session)
                aggregate = await ingest_parsed_rows(
                    service,
                    parsed_rows,
                    source="AMAZON_FBA_CSV",
                    fulfillment_channel=OrderFulfillmentChannel.AMAZON_FBA,
                    skip_existing=False,
                )
            job.orders_created = aggregate["new_orders"]
            job.items_created = aggregate["new_items"]
            job.orders_updated = aggregate["skipped_duplicates"]
            if aggregate["errors"]:
                job.warnings.extend(str(e) for e in aggregate["errors"][:10])

        # ── done ─────────────────────────────────────────────────────────
        job.phase = PHASE_DONE
        job.finished_at = _utcnow()
        job.status = STATUS_COMPLETED_WARN if job.warnings else STATUS_COMPLETED
        job.message = (
            f"Imported {job.orders_created} new order(s); "
            f"{job.counts.get(R_FOUND, 0)} buyer name(s) filled."
        )
    except asyncio.CancelledError:
        logger.info("FBA import job %s cancelled (abort)", job.job_id)
        job.status = STATUS_ABORTED
        job.finished_at = _utcnow()
        job.message = "Aborted — no partial import is left behind unless ingestion had started."
    except PipelineError as exc:
        logger.warning("FBA import job %s: bad input (%s)", job.job_id, exc)
        job.status = STATUS_FAILED
        job.finished_at = _utcnow()
        job.message = str(exc)
        job.last_error = str(exc)
    except Exception as exc:  # noqa: BLE001
        logger.exception("FBA import job %s failed", job.job_id)
        job.status = STATUS_FAILED
        job.finished_at = _utcnow()
        job.message = f"Import failed: {exc}"
        job.last_error = str(exc)[:300]
    finally:
        async with _JOB_LOCK:
            _LAST_JOB = job
            if _CURRENT_JOB is job:
                _CURRENT_JOB = None
            _CURRENT_TASK = None


# ── Public API (used by routes) ────────────────────────────────────────────
async def start_job(
    *, all_orders_txt: str, fulfillment_csv: str, triggered_by: str | None = None
) -> FbaImportJobState:
    global _CURRENT_JOB, _CURRENT_TASK
    async with _JOB_LOCK:
        if _is_active(_CURRENT_JOB):
            raise JobAlreadyRunning
        job = FbaImportJobState(job_id=uuid.uuid4().hex[:12], triggered_by=triggered_by)
        job.message = "Starting…"
        _CURRENT_JOB = job
        _CURRENT_TASK = asyncio.create_task(
            _process(job, all_orders_txt, fulfillment_csv)
        )
        return job


async def abort() -> FbaImportJobState:
    global _CURRENT_JOB, _LAST_JOB, _CURRENT_TASK
    job = _CURRENT_JOB
    if job is None:
        raise NoActiveJob
    job.cancel_requested = True
    job.message = "Aborting…"
    task = _CURRENT_TASK
    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
    if job.status not in _TERMINAL:
        job.status = STATUS_ABORTED
        job.finished_at = _utcnow()
        async with _JOB_LOCK:
            _LAST_JOB = job
            if _CURRENT_JOB is job:
                _CURRENT_JOB = None
            _CURRENT_TASK = None
    return job
