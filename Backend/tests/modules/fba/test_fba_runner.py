"""
Unit tests for the FBA import runner.

The Playwright scraper and the order-ingestion call are both faked, so these
exercise the orchestration (phases, buyer-name back-fill, auth-expired handling,
abort) without a browser or a database.
"""
import csv
import io

import pytest

import app.models  # noqa: F401  — resolve model circular imports
from app.modules.fba import runner
from app.modules.fba.scraper import (
    AUTH_LOGGED_IN,
    AUTH_SIGNED_OUT,
    BuyerNameResult,
    FbaAuthExpired,
)

ALL_ORDERS_HEADERS = [
    "amazon-order-id", "merchant-order-id", "purchase-date", "order-status",
    "fulfillment-channel", "product-name", "sku", "quantity", "item-price",
]
FULFILLMENT_HEADERS = ["Amazon Order Id", "Merchant Order Id", "Merchant SKU", "Buyer Name"]


def _inputs(order_ids, *, with_names=()):
    tbuf = io.StringIO()
    tw = csv.DictWriter(tbuf, fieldnames=ALL_ORDERS_HEADERS, delimiter="\t")
    tw.writeheader()
    for oid in order_ids:
        tw.writerow({
            "amazon-order-id": oid, "merchant-order-id": oid, "order-status": "Shipped",
            "fulfillment-channel": "Amazon", "sku": f"SKU-{oid}", "quantity": "1",
            "item-price": "10", "product-name": "Thing",
        })
    cbuf = io.StringIO()
    cw = csv.DictWriter(cbuf, fieldnames=FULFILLMENT_HEADERS)
    cw.writeheader()
    for oid in order_ids:
        cw.writerow({
            "Amazon Order Id": oid, "Merchant Order Id": oid, "Merchant SKU": f"SKU-{oid}",
            "Buyer Name": "Known Buyer" if oid in with_names else "",
        })
    return tbuf.getvalue(), cbuf.getvalue()


class FakeScraper:
    def __init__(self, *, names=None, raise_auth_after=None, auth=AUTH_LOGGED_IN, **_kw):
        self._names = names or {}
        self._raise_auth_after = raise_auth_after
        self._auth = auth
        self.calls = 0

    async def start(self):
        return None

    async def close(self):
        return None

    async def check_auth(self):
        return self._auth

    async def scrape_buyer_name(self, order_id):
        self.calls += 1
        if self._raise_auth_after is not None and self.calls > self._raise_auth_after:
            raise FbaAuthExpired("session gone")
        if order_id in self._names:
            return BuyerNameResult(buyer_name=self._names[order_id], detail="fake")
        return BuyerNameResult(detail="not found")


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    runner._CURRENT_JOB = None
    runner._LAST_JOB = None
    runner._CURRENT_TASK = None
    original = runner._scraper_factory
    # Stub out DB ingestion — return a fixed aggregate.
    ingested = {}

    async def _fake_ingest(_service, rows, **kwargs):
        ingested["rows"] = rows
        ingested["kwargs"] = kwargs
        return {"new_orders": len(rows), "new_items": len(rows), "skipped_duplicates": 0, "errors": []}

    monkeypatch.setattr("app.modules.orders.import_ingest.ingest_parsed_rows", _fake_ingest)

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_e):
            return False

    monkeypatch.setattr(runner, "async_session_factory", lambda: _FakeSession())
    monkeypatch.setattr(runner, "_build_service", lambda _s: object())
    runner._test_ingested = ingested
    yield
    runner._scraper_factory = original
    runner._CURRENT_JOB = runner._LAST_JOB = runner._CURRENT_TASK = None


async def _run_to_completion(txt, ff):
    job = await runner.start_job(all_orders_txt=txt, fulfillment_csv=ff)
    await runner._CURRENT_TASK
    return job


@pytest.mark.asyncio
async def test_happy_path_fills_names_and_ingests(monkeypatch):
    monkeypatch.setattr(
        runner, "_scraper_factory",
        lambda **kw: FakeScraper(names={"111": "Alice", "222": "Bob"}, **kw),
    )
    txt, ff = _inputs(["111", "222", "333"], with_names=["333"])
    job = await _run_to_completion(txt, ff)

    assert job.status == runner.STATUS_COMPLETED
    assert job.counts.get(runner.R_FOUND) == 2
    assert job.total_names == 2                      # 333 already had a name
    assert job.orders_created == 3
    ingested_rows = runner._test_ingested["rows"]
    names = {r["platform_order_id"]: r["customer_name"] for r in ingested_rows}
    assert names == {"111": "Alice", "222": "Bob", "333": "Known Buyer"}


@pytest.mark.asyncio
async def test_auth_expired_still_imports_without_names(monkeypatch):
    monkeypatch.setattr(
        runner, "_scraper_factory",
        lambda **kw: FakeScraper(names={"111": "Alice"}, raise_auth_after=1, **kw),
    )
    txt, ff = _inputs(["111", "222", "333"])
    job = await _run_to_completion(txt, ff)

    assert job.status == runner.STATUS_COMPLETED_WARN
    assert any("session" in w.lower() or "expired" in w.lower() for w in job.warnings)
    assert job.counts.get(runner.R_AUTH_EXPIRED, 0) >= 1
    assert job.orders_created == 3                   # imported anyway


@pytest.mark.asyncio
async def test_signed_out_check_skips_scrape_but_imports(monkeypatch):
    monkeypatch.setattr(
        runner, "_scraper_factory",
        lambda **kw: FakeScraper(auth=AUTH_SIGNED_OUT, **kw),
    )
    txt, ff = _inputs(["111", "222"])
    job = await _run_to_completion(txt, ff)

    assert job.status == runner.STATUS_COMPLETED_WARN
    assert job.counts.get(runner.R_AUTH_EXPIRED, 0) == 2
    assert job.orders_created == 2


@pytest.mark.asyncio
async def test_second_job_conflicts_while_running(monkeypatch):
    monkeypatch.setattr(runner, "_scraper_factory", lambda **kw: FakeScraper(**kw))
    txt, ff = _inputs(["111"])
    await runner.start_job(all_orders_txt=txt, fulfillment_csv=ff)
    with pytest.raises(runner.JobAlreadyRunning):
        await runner.start_job(all_orders_txt=txt, fulfillment_csv=ff)
    await runner._CURRENT_TASK


@pytest.mark.asyncio
async def test_bad_input_fails_cleanly(monkeypatch):
    monkeypatch.setattr(runner, "_scraper_factory", lambda **kw: FakeScraper(**kw))
    job = await _run_to_completion("garbage\n", "garbage\n")
    assert job.status == runner.STATUS_FAILED
    assert job.last_error
