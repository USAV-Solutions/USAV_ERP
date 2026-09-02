"""Smoke tests for the FBA import routes — handlers called directly, runner faked."""
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.models  # noqa: F401
from app.modules.fba import routes, runner
from app.modules.fba.routes import abort_import, import_status, period_hint


@pytest.fixture(autouse=True)
def _reset():
    runner._CURRENT_JOB = runner._LAST_JOB = runner._CURRENT_TASK = None
    yield
    runner._CURRENT_JOB = runner._LAST_JOB = runner._CURRENT_TASK = None


@pytest.mark.asyncio
async def test_status_is_idle_when_no_job():
    out = await import_status(_staff=MagicMock())
    assert out.status == "idle"
    assert out.job_id is None


@pytest.mark.asyncio
async def test_abort_without_job_is_409(monkeypatch):
    monkeypatch.setattr(routes.runner, "abort", AsyncMock(side_effect=runner.NoActiveJob))
    with pytest.raises(Exception) as excinfo:
        await abort_import(_staff=MagicMock())
    assert getattr(excinfo.value, "status_code", None) == 409


@pytest.mark.asyncio
async def test_period_hint_uses_last_order_date(monkeypatch):
    from datetime import datetime, timezone

    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = datetime(2026, 8, 20, tzinfo=timezone.utc)
    db.execute = AsyncMock(return_value=result)

    out = await period_hint(_staff=MagicMock(), db=db)
    assert out.last_import_date is not None
    assert out.option_days in (7, 15, 30, 60)
    assert {r.save_as for r in out.reports} == {"all_orders_txt", "fulfillment_csv"}
    assert out.reports[0].button == "Request Download"
    assert out.reports[1].button == "Request .csv Download"


@pytest.mark.asyncio
async def test_period_hint_defaults_widest_without_history(monkeypatch):
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=result)

    out = await period_hint(_staff=MagicMock(), db=db)
    assert out.last_import_date is None
    assert out.option_days == 60
