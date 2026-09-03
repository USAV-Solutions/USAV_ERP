"""
Tracking scrape job orchestrator.

One job at a time, held in module-level state (same pattern as the Zoho bulk-sync
job in ``app/modules/inventory/routes/zoho.py``). The job runs as a single
``asyncio`` task; per-order results are committed to the database as they land so
progress survives a crash or redeploy.

Lifecycle::

    idle → running ──(rate limit ×N)──▶ paused_rate_limit ──(probe OK)──▶ running
                │                                                            │
                ├────────────────── completed / aborted / failed ◀───────────┘

While ``paused_rate_limit`` the browser is closed. Resuming is gated on a
successful single-order probe — never on the advisory cooldown timer. When
``auto_probe`` is on, the runner probes itself on an interval (with exponential
backoff) and resumes automatically once the probe clears.
"""
from __future__ import annotations

import asyncio
import logging
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select

from app.core.config import settings
from app.core.database import async_session_factory
from app.models.entities import ZohoSyncStatus
from app.modules.orders.models import Order, OrderFulfillmentChannel, ShippingStatus
from app.modules.tracking.scraper import (
    ERROR,
    PERSISTABLE,
    RATE_LIMITED,
    UNKNOWN,
    ScrapeResult,
    ScraperProtocol,
    TrackingScraper,
    parcelsapp_url,
)
from app.modules.tracking.status_mapping import map_scraped_status

logger = logging.getLogger(__name__)

# ── Job statuses ─────────────────────────────────────────────────────────────
STATUS_RUNNING = "running"
STATUS_PAUSED = "paused_rate_limit"
STATUS_COMPLETED = "completed"
STATUS_ABORTED = "aborted"
STATUS_FAILED = "failed"
_TERMINAL = {STATUS_COMPLETED, STATUS_ABORTED, STATUS_FAILED}
_ACTIVE = {STATUS_RUNNING, STATUS_PAUSED}

# Give up on a single tracking number after this many scrape attempts so one bad
# entry can never wedge the queue.
_MAX_ATTEMPTS_PER_ITEM = 4
_SCRAPE_TIMEOUT_SECONDS = 80  # nav (25s) + API poll (30s) + slack


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class JobAlreadyRunning(RuntimeError):
    pass


class NoPausedJob(RuntimeError):
    pass


class ProbeNotCleared(RuntimeError):
    pass


# ── State ────────────────────────────────────────────────────────────────────
@dataclass
class TrackingItemState:
    order_number: str
    tracking_number: str
    order_ids: list[int]
    result: str | None = None
    detail: str | None = None  # human-readable diagnostic (latest event / error)
    checked_at: datetime | None = None
    attempts: int = 0
    # order_ids whose shipping_status actually flipped (→ marked DIRTY for Zoho).
    changed_order_ids: list[int] = field(default_factory=list)

    @property
    def parcelsapp_url(self) -> str:
        return parcelsapp_url(self.tracking_number)


@dataclass
class TrackingJobState:
    job_id: str
    status: str = STATUS_RUNNING
    started_at: datetime = field(default_factory=_utcnow)
    finished_at: datetime | None = None
    triggered_by: str | None = None
    items: list[TrackingItemState] = field(default_factory=list)
    cursor: int = 0  # index of the next item to scrape
    counts: dict[str, int] = field(default_factory=dict)
    current: TrackingItemState | None = None
    cooldown_until: datetime | None = None
    consecutive_rate_limited: int = 0
    auto_probe: bool = True
    auto_probe_interval_minutes: int = field(
        default_factory=lambda: settings.tracking_auto_probe_interval_minutes
    )
    last_probe_result: str | None = None  # OK | RATE_LIMITED | ERROR
    last_probe_at: datetime | None = None
    cancel_requested: bool = False
    message: str | None = None
    last_error: str | None = None  # most recent ERROR/UNKNOWN detail, for debugging

    @property
    def total(self) -> int:
        return len(self.items)

    @property
    def processed(self) -> int:
        return sum(1 for it in self.items if it.result is not None)

    @property
    def remaining(self) -> int:
        return self.total - self.processed

    @property
    def changed_order_ids(self) -> list[int]:
        """Distinct order ids whose shipping_status flipped → need a Zoho push."""
        return sorted({oid for it in self.items for oid in it.changed_order_ids})


# Module-level singletons.
_JOB_LOCK = asyncio.Lock()
_CURRENT_JOB: TrackingJobState | None = None
_LAST_JOB: TrackingJobState | None = None
_CURRENT_TASK: asyncio.Task | None = None

# Seam for tests — overridden with a fake that yields scripted ScrapeResults.
_scraper_factory = TrackingScraper


def set_scraper_factory(factory) -> None:
    """Test hook: swap the Playwright scraper for a fake."""
    global _scraper_factory
    _scraper_factory = factory


def _is_active(job: TrackingJobState | None) -> bool:
    return job is not None and job.status in _ACTIVE


def get_state() -> TrackingJobState | None:
    """The current job if one exists, otherwise the most recent finished job."""
    return _CURRENT_JOB or _LAST_JOB


# ── Eligible-order query ─────────────────────────────────────────────────────
def _eligible_where():
    cutoff = _utcnow() - timedelta(hours=settings.tracking_freshness_hours)
    return (
        Order.shipping_status == ShippingStatus.PENDING,
        Order.source != "AMAZON_FBA_CSV",
        Order.fulfillment_channel != OrderFulfillmentChannel.AMAZON_FBA,
        Order.tracking_number.is_not(None),
        func.trim(Order.tracking_number) != "",
        func.upper(func.trim(Order.tracking_number)).not_like("TBA%"),
        or_(
            Order.tracking_last_checked_at.is_(None),
            Order.tracking_last_checked_at < cutoff,
        ),
    )


async def count_eligible(db) -> int:
    stmt = select(func.count()).select_from(Order).where(*_eligible_where())
    return int((await db.execute(stmt)).scalar_one())


async def _load_eligible_items(db) -> list[TrackingItemState]:
    stmt = (
        select(
            Order.id,
            Order.external_order_id,
            Order.external_order_number,
            Order.tracking_number,
        )
        .where(*_eligible_where())
        .order_by(Order.ordered_at.desc().nulls_last())
    )
    rows = (await db.execute(stmt)).all()

    grouped: dict[str, TrackingItemState] = {}
    for order_id, ext_id, ext_num, tracking in rows:
        key = (tracking or "").strip()
        if not key:
            continue
        item = grouped.get(key)
        if item is None:
            item = TrackingItemState(
                order_number=(ext_num or ext_id or str(order_id)),
                tracking_number=key,
                order_ids=[],
            )
            grouped[key] = item
        item.order_ids.append(order_id)
    return list(grouped.values())


# ── Result persistence ──────────────────────────────────────────────────────
async def _apply_result(item: TrackingItemState, result: ScrapeResult) -> None:
    """Persist a confident result; leave the order untouched otherwise."""
    item.detail = result.detail or None
    if result.status not in PERSISTABLE:
        item.result = result.status
        item.checked_at = _utcnow()
        return

    mapped = map_scraped_status(result.status)
    now = _utcnow()
    async with async_session_factory() as db:
        orders = (
            await db.execute(select(Order).where(Order.id.in_(item.order_ids)))
        ).scalars().all()
        changed: list[int] = []
        for order in orders:
            order.tracking_last_checked_at = now
            if mapped is not None and order.shipping_status != mapped:
                order.shipping_status = mapped
                order.zoho_sync_status = ZohoSyncStatus.DIRTY
                changed.append(order.id)
        await db.commit()

    item.result = result.status
    item.checked_at = now
    item.changed_order_ids = changed


def _count(job: TrackingJobState, status: str) -> None:
    job.counts[status] = job.counts.get(status, 0) + 1


# ── Core loop ───────────────────────────────────────────────────────────────
async def _scrape_item(scraper: ScraperProtocol, item: TrackingItemState) -> ScrapeResult:
    item.attempts += 1
    try:
        return await asyncio.wait_for(
            scraper.scrape(item.tracking_number), timeout=_SCRAPE_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        return ScrapeResult(ERROR, "scrape timed out")
    except Exception as exc:  # noqa: BLE001
        return ScrapeResult(ERROR, str(exc))


async def _process(job: TrackingJobState) -> None:
    """Run the queue until it is exhausted, aborted, or rate-limit-paused."""
    global _CURRENT_JOB, _LAST_JOB, _CURRENT_TASK

    min_delay = settings.tracking_scraper_min_delay_seconds
    max_delay = settings.tracking_scraper_max_delay_seconds

    try:
        async with _scraper_factory(headless=settings.tracking_scraper_headless) as scraper:
            job.status = STATUS_RUNNING
            job.message = None

            while job.cursor < len(job.items):
                if job.cancel_requested:
                    break

                item = job.items[job.cursor]

                if item.attempts >= _MAX_ATTEMPTS_PER_ITEM:
                    item.result = item.result or ERROR
                    item.checked_at = _utcnow()
                    _count(job, item.result)
                    job.cursor += 1
                    continue

                job.current = item
                result = await _scrape_item(scraper, item)
                job.current = None
                logger.info(
                    "tracking job=%s [%s/%s] %s → %s (%s)",
                    job.job_id, job.cursor + 1, job.total,
                    item.tracking_number, result.status, result.detail,
                )
                if result.status in (ERROR, UNKNOWN):
                    job.last_error = f"{item.tracking_number}: {result.status} — {result.detail}"

                if result.status == RATE_LIMITED:
                    job.consecutive_rate_limited += 1
                    if job.consecutive_rate_limited >= settings.tracking_rate_limit_threshold:
                        _enter_cooldown(job)
                        return
                    # A lone hit is usually a label parcelsapp has not ingested
                    # yet — back off briefly and retry the same item.
                    await asyncio.sleep(random.uniform(max_delay, max_delay * 2))
                    continue

                job.consecutive_rate_limited = 0
                await _apply_result(item, result)
                _count(job, result.status)
                job.cursor += 1
                await asyncio.sleep(random.uniform(min_delay, max_delay))

        job.status = STATUS_ABORTED if job.cancel_requested else STATUS_COMPLETED
        job.finished_at = _utcnow()
        job.current = None
        if job.status == STATUS_COMPLETED:
            job.message = "All eligible orders checked."
        else:
            job.message = "Aborted — progress up to here is saved."
    except asyncio.CancelledError:
        # Deliberate abort (the task was cancelled). Translate to a clean state.
        logger.info("Tracking job %s cancelled (abort)", job.job_id)
        job.status = STATUS_ABORTED
        job.message = "Aborted — progress up to here is saved."
        job.finished_at = _utcnow()
        job.current = None
    except Exception as exc:  # noqa: BLE001
        logger.exception("Tracking job %s failed", job.job_id)
        job.status = STATUS_FAILED
        job.message = f"Scraper error: {exc}"
        job.last_error = str(exc)[:300]
        job.finished_at = _utcnow()
        job.current = None
    finally:
        async with _JOB_LOCK:
            if job.status in _TERMINAL:
                _LAST_JOB = job
                if _CURRENT_JOB is job:
                    _CURRENT_JOB = None
                _CURRENT_TASK = None
            elif job.status == STATUS_PAUSED and job.auto_probe:
                _CURRENT_TASK = asyncio.create_task(_auto_probe_loop(job))
            else:
                _CURRENT_TASK = None


def _enter_cooldown(job: TrackingJobState) -> None:
    job.status = STATUS_PAUSED
    job.finished_at = None
    job.current = None
    job.cooldown_until = _utcnow() + timedelta(minutes=settings.tracking_cooldown_minutes)
    job.message = (
        f"Rate limit reached after {job.processed} checks. parcelsapp is "
        f"throttling this server — progress is saved."
    )
    logger.warning("Tracking job %s paused on rate limit at %s/%s",
                   job.job_id, job.processed, job.total)


# ── Probe & resume ──────────────────────────────────────────────────────────
async def _run_probe(job: TrackingJobState) -> bool:
    """Scrape a single remaining order to test whether the block has cleared."""
    remaining = [it for it in job.items if it.result is None]
    job.last_probe_at = _utcnow()

    if not remaining:
        job.last_probe_result = "OK"
        return True

    item = remaining[0]
    try:
        async with _scraper_factory(headless=settings.tracking_scraper_headless) as scraper:
            result = await _scrape_item(scraper, item)
    except Exception as exc:  # noqa: BLE001
        job.last_probe_result = "ERROR"
        job.message = f"Probe failed: {exc}"
        return False

    if result.status == RATE_LIMITED:
        job.last_probe_result = "RATE_LIMITED"
        if item.attempts >= _MAX_ATTEMPTS_PER_ITEM:
            # This tracking number is stuck (likely unknown to parcelsapp, not a
            # real block). Skip it so it can't wedge the queue forever.
            item.result = RATE_LIMITED
            item.checked_at = _utcnow()
            _count(job, RATE_LIMITED)
            if job.cursor < len(job.items) and job.items[job.cursor] is item:
                job.cursor += 1
            job.message = "Skipped a stuck tracking number; still throttled overall."
        else:
            job.message = "Still throttled — waiting longer before the next attempt."
        return False

    if result.status == ERROR:
        job.last_probe_result = "ERROR"
        job.message = f"Probe error: {result.detail}"
        return False

    await _apply_result(item, result)
    _count(job, result.status)
    if job.cursor < len(job.items) and job.items[job.cursor] is item:
        job.cursor += 1
    job.last_probe_result = "OK"
    job.consecutive_rate_limited = 0
    job.message = "Probe cleared — safe to resume."
    return True


async def _resume_processing(job: TrackingJobState) -> None:
    job.status = STATUS_RUNNING
    job.cooldown_until = None
    job.consecutive_rate_limited = 0
    job.last_probe_result = None
    job.auto_probe_interval_minutes = settings.tracking_auto_probe_interval_minutes
    await _process(job)


async def _auto_probe_loop(job: TrackingJobState) -> None:
    """While paused with auto-probe on: probe on an interval, resume when clear."""
    global _CURRENT_TASK
    try:
        while job.status == STATUS_PAUSED and job.auto_probe and not job.cancel_requested:
            await asyncio.sleep(job.auto_probe_interval_minutes * 60)
            if job.status != STATUS_PAUSED or not job.auto_probe or job.cancel_requested:
                return
            if await _run_probe(job):
                await _resume_processing(job)  # continues in this task
                return
            job.auto_probe_interval_minutes = min(
                job.auto_probe_interval_minutes * 2,
                settings.tracking_auto_probe_max_interval_minutes,
            )
            job.cooldown_until = _utcnow() + timedelta(
                minutes=job.auto_probe_interval_minutes
            )
    finally:
        async with _JOB_LOCK:
            if _CURRENT_TASK is asyncio.current_task():
                _CURRENT_TASK = None


def _spawn(coro) -> None:
    global _CURRENT_TASK
    _CURRENT_TASK = asyncio.create_task(coro)


# ── Public API (used by routes) ─────────────────────────────────────────────
async def start_job(
    db, *, triggered_by: str | None = None, auto_probe: bool = True
) -> TrackingJobState:
    global _CURRENT_JOB, _LAST_JOB
    async with _JOB_LOCK:
        if _is_active(_CURRENT_JOB):
            raise JobAlreadyRunning
        items = await _load_eligible_items(db)
        job = TrackingJobState(
            job_id=uuid.uuid4().hex[:12],
            items=items,
            triggered_by=triggered_by,
            auto_probe=auto_probe,
        )
        if not items:
            job.status = STATUS_COMPLETED
            job.finished_at = _utcnow()
            job.message = "No eligible orders to check."
            _LAST_JOB = job
            _CURRENT_JOB = None
            return job
        job.message = f"Checking {len(items)} tracking numbers."
        _CURRENT_JOB = job
        _spawn(_process(job))
        return job


async def probe() -> TrackingJobState:
    job = _CURRENT_JOB
    if job is None or job.status != STATUS_PAUSED:
        raise NoPausedJob
    await _run_probe(job)
    return job


async def resume() -> TrackingJobState:
    job = _CURRENT_JOB
    if job is None or job.status != STATUS_PAUSED:
        raise NoPausedJob
    if job.last_probe_result != "OK":
        raise ProbeNotCleared
    _spawn(_resume_processing(job))
    return job


async def abort() -> TrackingJobState:
    global _CURRENT_JOB, _LAST_JOB, _CURRENT_TASK
    job = _CURRENT_JOB
    if job is None:
        raise NoPausedJob

    job.cancel_requested = True
    job.message = "Aborting…"
    task = _CURRENT_TASK

    if task is not None and not task.done():
        # Interrupt an in-flight scrape or a cooldown wait immediately. For a
        # running job _process() catches CancelledError and finalizes itself
        # (its `finally` clears the module globals); for a paused job the task
        # is the auto-probe loop, which we finalize here.
        task.cancel()
        if job.status != STATUS_PAUSED:
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    if job.status != STATUS_ABORTED:
        job.status = STATUS_ABORTED
        job.finished_at = _utcnow()
        job.current = None
        job.message = "Aborted — progress up to here is saved."
        async with _JOB_LOCK:
            _LAST_JOB = job
            if _CURRENT_JOB is job:
                _CURRENT_JOB = None
            _CURRENT_TASK = None
    return job


async def set_auto_probe(enabled: bool) -> TrackingJobState:
    job = _CURRENT_JOB
    if job is None:
        raise NoPausedJob
    job.auto_probe = enabled
    if enabled and job.status == STATUS_PAUSED and (
        _CURRENT_TASK is None or _CURRENT_TASK.done()
    ):
        job.auto_probe_interval_minutes = settings.tracking_auto_probe_interval_minutes
        _spawn(_auto_probe_loop(job))
    return job
