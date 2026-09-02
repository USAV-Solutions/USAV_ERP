"""Smoke tests for the tracking routes — handlers called directly, runner faked."""
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.models  # noqa: F401
from app.modules.tracking import routes, runner
from app.modules.tracking.routes import (
    abort_sync,
    eligible_count,
    resume_sync,
    start_sync,
    sync_status,
)


@pytest.fixture(autouse=True)
def _reset():
    runner._CURRENT_JOB = None
    runner._LAST_JOB = None
    runner._CURRENT_TASK = None
    yield
    runner._CURRENT_JOB = None
    runner._LAST_JOB = None
    runner._CURRENT_TASK = None


@pytest.mark.asyncio
async def test_status_is_idle_when_no_job():
    out = await sync_status(_staff=MagicMock())
    assert out.status == "idle"
    assert out.job_id is None


@pytest.mark.asyncio
async def test_eligible_count_passthrough(monkeypatch):
    monkeypatch.setattr(runner, "count_eligible", AsyncMock(return_value=7))
    out = await eligible_count(_staff=MagicMock(), db=MagicMock())
    assert out.count == 7


@pytest.mark.asyncio
async def test_start_conflicts_when_job_running(monkeypatch):
    monkeypatch.setattr(
        routes.runner, "start_job", AsyncMock(side_effect=runner.JobAlreadyRunning)
    )
    staff = MagicMock()
    staff.username = "alice"
    with pytest.raises(Exception) as excinfo:
        await start_sync(staff=staff, db=MagicMock())
    assert getattr(excinfo.value, "status_code", None) == 409


@pytest.mark.asyncio
async def test_resume_requires_probe(monkeypatch):
    monkeypatch.setattr(
        routes.runner, "resume", AsyncMock(side_effect=runner.ProbeNotCleared)
    )
    with pytest.raises(Exception) as excinfo:
        await resume_sync(_staff=MagicMock())
    assert getattr(excinfo.value, "status_code", None) == 409


@pytest.mark.asyncio
async def test_abort_conflicts_when_no_job(monkeypatch):
    monkeypatch.setattr(routes.runner, "abort", AsyncMock(side_effect=runner.NoPausedJob))
    with pytest.raises(Exception) as excinfo:
        await abort_sync(_staff=MagicMock())
    assert getattr(excinfo.value, "status_code", None) == 409
