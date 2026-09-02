"""
Unit tests for the tracking scrape runner.

The Playwright scraper and the database session factory are both faked, so these
exercise the orchestration logic (queue, rate-limit pause, probe-gated resume,
result persistence) without a browser or a database.
"""
import asyncio
from unittest.mock import MagicMock

import pytest

import app.models  # noqa: F401  — resolve model circular imports
from app.models.entities import ZohoSyncStatus
from app.modules.orders.models import Order, ShippingStatus
from app.modules.tracking import runner
from app.modules.tracking.scraper import (
    DELIVERED,
    NOT_FOUND,
    PENDING,
    RATE_LIMITED,
    SHIPPING,
    ScrapeResult,
    _classify_dom,
    classify_api,
)
from app.modules.tracking.status_mapping import map_scraped_status


# ── Fakes ───────────────────────────────────────────────────────────────────
class FakeScraper:
    def __init__(self, responder, **_kw):
        self._responder = responder
        self.calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def scrape(self, tracking_number):
        self.calls += 1
        res = self._responder(tracking_number, self.calls)
        if asyncio.iscoroutine(res):
            res = await res
        return res if isinstance(res, ScrapeResult) else ScrapeResult(res)


class FakeSession:
    """Minimal async-context session that records commits and mutations."""

    last_orders: list = []
    commits = 0

    def __init__(self, orders):
        self._orders = orders

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def execute(self, _stmt):
        result = MagicMock()
        result.scalars.return_value.all.return_value = self._orders
        return result

    async def commit(self):
        FakeSession.commits += 1


@pytest.fixture(autouse=True)
def _reset_runner():
    runner._CURRENT_JOB = None
    runner._LAST_JOB = None
    runner._CURRENT_TASK = None
    original_factory = runner._scraper_factory
    FakeSession.commits = 0
    yield
    runner._scraper_factory = original_factory
    runner._CURRENT_JOB = None
    runner._LAST_JOB = None
    runner._CURRENT_TASK = None


def _db_returning(rows):
    db = MagicMock()

    async def _execute(_stmt):
        result = MagicMock()
        result.all.return_value = rows
        result.scalar_one.return_value = len(rows)
        return result

    db.execute = _execute
    return db


def _order(shipping=ShippingStatus.PENDING, zoho=ZohoSyncStatus.SYNCED, order_id=1):
    o = MagicMock(spec=Order)
    o.id = order_id
    o.shipping_status = shipping
    o.zoho_sync_status = zoho
    o.tracking_last_checked_at = None
    return o


async def _drain():
    """Await whatever task the runner currently has in flight."""
    task = runner._CURRENT_TASK
    if task is not None:
        await task


# ── Tests ───────────────────────────────────────────────────────────────────
def test_classify_api():
    assert classify_api({"error": "RELOAD"}).status == RATE_LIMITED
    assert classify_api({"error": "NO_DATA"}).status == NOT_FOUND
    assert classify_api({"status": "transit", "states": [{"status": "In Transit"}]}).status == SHIPPING
    assert classify_api(
        {"status": "transit", "states": [{"status": "Delivered, In/At Mailbox"}]}
    ).status == DELIVERED
    assert classify_api({"status": "delivered", "states": []}).status == DELIVERED
    assert classify_api(
        {"status": "pending", "states": [{"status": "Shipping Label Created"}]}
    ).status == PENDING
    # parcelsapp reports "transit" prematurely for label-only parcels
    assert classify_api(
        {"status": "transit", "states": [{"status": "Shipping Label Created, USPS Awaiting Item"}]}
    ).status == PENDING
    assert classify_api({"status": "pending", "states": []}).status == NOT_FOUND
    assert classify_api({"status": "archive", "states": [{"status": "DELIVERED"}]}).status == DELIVERED
    assert classify_api("garbage").status == "UNKNOWN"


def test_classify_dom_fallback():
    assert _classify_dom("information has not been found yet").status == RATE_LIMITED
    assert _classify_dom("shipping label created").status == PENDING
    assert _classify_dom("delivered, front door").status == DELIVERED
    assert _classify_dom("arrived at usps regional facility").status == SHIPPING


def test_status_mapping_parity():
    assert map_scraped_status("DELIVERED") is ShippingStatus.DELIVERED
    assert map_scraped_status("shipping") is ShippingStatus.SHIPPING
    assert map_scraped_status("SHIPPED") is ShippingStatus.SHIPPING
    assert map_scraped_status("PENDING") is None
    assert map_scraped_status("NOT_FOUND") is None
    assert map_scraped_status("") is None


@pytest.mark.asyncio
async def test_start_with_no_eligible_orders_completes_immediately():
    job = await runner.start_job(_db_returning([]), auto_probe=False)
    assert job.status == runner.STATUS_COMPLETED
    assert job.total == 0
    assert runner._CURRENT_JOB is None


@pytest.mark.asyncio
async def test_persists_delivered_and_marks_dirty(monkeypatch):
    monkeypatch.setattr(runner.settings, "tracking_scraper_min_delay_seconds", 0.0)
    monkeypatch.setattr(runner.settings, "tracking_scraper_max_delay_seconds", 0.0)
    order = _order(order_id=42)
    monkeypatch.setattr(runner, "async_session_factory", lambda: FakeSession([order]))
    runner.set_scraper_factory(
        lambda **kw: FakeScraper(lambda tn, n: ScrapeResult(DELIVERED))
    )

    rows = [(42, "SO-1", "SO-1", "1Z999")]
    await runner.start_job(_db_returning(rows), auto_probe=False)
    await _drain()

    job = runner.get_state()
    assert job.status == runner.STATUS_COMPLETED
    assert job.counts.get(DELIVERED) == 1
    assert order.shipping_status is ShippingStatus.DELIVERED
    assert order.zoho_sync_status is ZohoSyncStatus.DIRTY
    assert FakeSession.commits == 1
    assert job.items[0].changed_order_ids == [42]
    assert job.changed_order_ids == [42]


@pytest.mark.asyncio
async def test_single_rate_limit_does_not_pause(monkeypatch):
    monkeypatch.setattr(runner.settings, "tracking_scraper_min_delay_seconds", 0.0)
    monkeypatch.setattr(runner.settings, "tracking_scraper_max_delay_seconds", 0.0)
    monkeypatch.setattr(runner, "async_session_factory", lambda: FakeSession([_order()]))

    # First call rate-limited, every retry succeeds.
    def responder(tn, n):
        return ScrapeResult(RATE_LIMITED) if n == 1 else ScrapeResult(SHIPPING)

    runner.set_scraper_factory(lambda **kw: FakeScraper(responder))
    await runner.start_job(_db_returning([(1, "SO-1", "SO-1", "T1")]), auto_probe=False)
    await _drain()

    job = runner.get_state()
    assert job.status == runner.STATUS_COMPLETED
    assert job.processed == 1


@pytest.mark.asyncio
async def test_consecutive_rate_limits_pause_without_advancing(monkeypatch):
    monkeypatch.setattr(runner.settings, "tracking_scraper_min_delay_seconds", 0.0)
    monkeypatch.setattr(runner.settings, "tracking_scraper_max_delay_seconds", 0.0)
    monkeypatch.setattr(runner.settings, "tracking_rate_limit_threshold", 3)
    runner.set_scraper_factory(
        lambda **kw: FakeScraper(lambda tn, n: ScrapeResult(RATE_LIMITED))
    )

    rows = [(1, "SO-1", "SO-1", "T1"), (2, "SO-2", "SO-2", "T2")]
    await runner.start_job(_db_returning(rows), auto_probe=False)
    await _drain()

    job = runner.get_state()
    assert job.status == runner.STATUS_PAUSED
    assert job.cursor == 0  # nothing consumed
    assert job.processed == 0
    assert job.cooldown_until is not None
    assert runner._CURRENT_JOB is job  # still the active job


@pytest.mark.asyncio
async def test_resume_requires_cleared_probe(monkeypatch):
    monkeypatch.setattr(runner.settings, "tracking_scraper_min_delay_seconds", 0.0)
    monkeypatch.setattr(runner.settings, "tracking_scraper_max_delay_seconds", 0.0)
    monkeypatch.setattr(runner, "async_session_factory", lambda: FakeSession([_order()]))

    state = {"blocked": True}

    def responder(tn, n):
        return ScrapeResult(RATE_LIMITED) if state["blocked"] else ScrapeResult(DELIVERED)

    runner.set_scraper_factory(lambda **kw: FakeScraper(responder))
    await runner.start_job(_db_returning([(1, "SO-1", "SO-1", "T1")]), auto_probe=False)
    await _drain()
    assert runner.get_state().status == runner.STATUS_PAUSED

    with pytest.raises(runner.ProbeNotCleared):
        await runner.resume()

    # Probe while still blocked → stays paused.
    await runner.probe()
    assert runner.get_state().last_probe_result == "RATE_LIMITED"
    with pytest.raises(runner.ProbeNotCleared):
        await runner.resume()

    # Unblock, probe clears, resume runs to completion.
    state["blocked"] = False
    await runner.probe()
    assert runner.get_state().last_probe_result == "OK"
    await runner.resume()
    await _drain()
    assert runner.get_state().status == runner.STATUS_COMPLETED


@pytest.mark.asyncio
async def test_abort_running_job(monkeypatch):
    monkeypatch.setattr(runner.settings, "tracking_scraper_min_delay_seconds", 0.0)
    monkeypatch.setattr(runner.settings, "tracking_scraper_max_delay_seconds", 0.0)
    monkeypatch.setattr(runner, "async_session_factory", lambda: FakeSession([_order()]))

    async def slow_scrape(tn, n):
        await asyncio.sleep(0.02)
        return ScrapeResult(SHIPPING)

    runner.set_scraper_factory(lambda **kw: FakeScraper(slow_scrape))
    rows = [(i, f"SO-{i}", f"SO-{i}", f"T{i}") for i in range(20)]
    await runner.start_job(_db_returning(rows), auto_probe=False)
    await asyncio.sleep(0.03)
    await runner.abort()
    await _drain()

    job = runner.get_state()
    assert job.status == runner.STATUS_ABORTED
    assert job.processed < job.total
