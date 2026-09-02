"""
Tracking scraper endpoints.

Manually-triggered, one-at-a-time background job that refreshes order
``shipping_status`` from parcelsapp.com. All endpoints require ADMIN or
SALES_REP (same as the ``SHIPPING_STATUS_CSV`` import this replaces).

    GET   /api/v1/tracking/eligible          → eligible order count (button badge)
    POST  /api/v1/tracking/sync/start        → start a job (409 if one is active)
    GET   /api/v1/tracking/sync/status       → poll job state (status "idle" if none)
    POST  /api/v1/tracking/sync/probe        → scrape one order to test the block
    POST  /api/v1/tracking/sync/resume       → resume after a cleared probe
    POST  /api/v1/tracking/sync/abort        → stop the job
    PATCH /api/v1/tracking/sync/auto-probe   → toggle auto-probe
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminOrSalesUser
from app.core.database import get_db
from app.modules.tracking import runner
from app.modules.tracking.schemas import (
    AutoProbeIn,
    EligibleCountOut,
    ProbeResultOut,
    TrackingJobOut,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tracking", tags=["Tracking"])


def _current() -> TrackingJobOut:
    job = runner.get_state()
    return TrackingJobOut.from_state(job) if job else TrackingJobOut.idle()


@router.get("/eligible", response_model=EligibleCountOut)
async def eligible_count(
    _staff: AdminOrSalesUser,
    db: AsyncSession = Depends(get_db),
):
    return EligibleCountOut(count=await runner.count_eligible(db))


@router.post(
    "/sync/start",
    response_model=TrackingJobOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_sync(
    staff: AdminOrSalesUser,
    db: AsyncSession = Depends(get_db),
):
    try:
        job = await runner.start_job(db, triggered_by=staff.username)
    except runner.JobAlreadyRunning:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A tracking sync is already running. Open the monitor to view it.",
        )
    logger.info("Tracking sync started by %s (%s orders)", staff.username, job.total)
    return TrackingJobOut.from_state(job)


@router.get("/sync/status", response_model=TrackingJobOut)
async def sync_status(_staff: AdminOrSalesUser):
    return _current()


@router.post("/sync/probe", response_model=ProbeResultOut)
async def probe_one(_staff: AdminOrSalesUser):
    try:
        job = await runner.probe()
    except runner.NoPausedJob:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No paused job to probe.",
        )
    return ProbeResultOut(
        result=job.last_probe_result,
        job=TrackingJobOut.from_state(job),
    )


@router.post(
    "/sync/resume",
    response_model=TrackingJobOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def resume_sync(_staff: AdminOrSalesUser):
    try:
        job = await runner.resume()
    except runner.NoPausedJob:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="No paused job to resume."
        )
    except runner.ProbeNotCleared:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Run a probe first — resume unlocks only after a probe succeeds.",
        )
    return TrackingJobOut.from_state(job)


@router.post("/sync/abort", response_model=TrackingJobOut)
async def abort_sync(_staff: AdminOrSalesUser):
    try:
        job = await runner.abort()
    except runner.NoPausedJob:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="No job to abort."
        )
    return TrackingJobOut.from_state(job)


@router.patch("/sync/auto-probe", response_model=TrackingJobOut)
async def toggle_auto_probe(body: AutoProbeIn, _staff: AdminOrSalesUser):
    try:
        job = await runner.set_auto_probe(body.enabled)
    except runner.NoPausedJob:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="No active job."
        )
    return TrackingJobOut.from_state(job)
