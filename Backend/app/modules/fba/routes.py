"""
FBA import endpoints.

Manually-triggered, one-at-a-time background job that merges the two raw Seller
Central exports, scrapes missing buyer names, and ingests the orders through the
existing ``AMAZON_FBA_CSV`` path. All endpoints require ADMIN or SALES_REP (same
as the CSV import this replaces).

    POST /api/v1/fba/import/start        multipart: all_orders_txt + fulfillment_csv
    GET  /api/v1/fba/import/status       poll job state ("idle" if none)
    POST /api/v1/fba/import/abort        stop the job
    GET  /api/v1/fba/import/period-hint  recommended Seller Central report window
    POST /api/v1/fba/import/auth-check   is the Chromium profile still logged in?
"""
import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminOrSalesUser
from app.core.config import settings
from app.core.database import get_db
from app.modules.fba import runner
from app.modules.fba.pipeline import pick_period_days
from app.modules.fba.schemas import (
    FbaAuthCheckOut,
    FbaImportJobOut,
    FbaPeriodHintOut,
    FbaReportHint,
)
from app.modules.orders.models import Order, OrderFulfillmentChannel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/fba", tags=["FBA Import"])

_MAX_UPLOAD_BYTES = 40 * 1024 * 1024  # generous; the reports are text


def _current() -> FbaImportJobOut:
    job = runner.get_state()
    return FbaImportJobOut.from_state(job) if job else FbaImportJobOut.idle()


async def _decode_upload(file: UploadFile, label: str, *, want_ext: str) -> str:
    if not file.filename or not file.filename.lower().endswith(want_ext):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{label} must be a {want_ext} file.",
        )
    raw = await file.read()
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"{label} is too large.",
        )
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"{label} could not be decoded as text.",
    )


@router.post(
    "/import/start",
    response_model=FbaImportJobOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_import(
    staff: AdminOrSalesUser,
    all_orders_txt: UploadFile = File(...),
    fulfillment_csv: UploadFile = File(...),
):
    txt = await _decode_upload(all_orders_txt, "All-Orders report", want_ext=".txt")
    csv_text = await _decode_upload(fulfillment_csv, "Fulfilment report", want_ext=".csv")
    try:
        job = await runner.start_job(
            all_orders_txt=txt,
            fulfillment_csv=csv_text,
            triggered_by=staff.username,
        )
    except runner.JobAlreadyRunning:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An FBA import is already running. Open the monitor to view it.",
        )
    logger.info("FBA import started by %s (job %s)", staff.username, job.job_id)
    return FbaImportJobOut.from_state(job)


@router.get("/import/status", response_model=FbaImportJobOut)
async def import_status(_staff: AdminOrSalesUser):
    return _current()


@router.post("/import/abort", response_model=FbaImportJobOut)
async def abort_import(_staff: AdminOrSalesUser):
    try:
        job = await runner.abort()
    except runner.NoActiveJob:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="No job to abort."
        )
    return FbaImportJobOut.from_state(job)


@router.get("/import/period-hint", response_model=FbaPeriodHintOut)
async def period_hint(
    _staff: AdminOrSalesUser,
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Order.ordered_at)
        .where(Order.fulfillment_channel == OrderFulfillmentChannel.AMAZON_FBA)
        .where(Order.ordered_at.is_not(None))
        .order_by(Order.ordered_at.desc())
        .limit(1)
    )
    last_dt = (await db.execute(stmt)).scalar_one_or_none()

    today = datetime.now(timezone.utc).date()
    if last_dt is None:
        days_needed = 60
    else:
        days_needed = max((today - last_dt.date()).days + 1, 1)
    option_days = pick_period_days(days_needed)

    reports = [
        FbaReportHint(
            name="All Orders report (.txt)",
            url="https://sellercentral.amazon.com/reportcentral/FlatFileAllOrdersReport/1",
            button="Request Download",
            file_format="Tab-delimited .txt",
            save_as="all_orders_txt",
        ),
        FbaReportHint(
            name="Amazon Fulfilled Shipments report (.csv)",
            url="https://sellercentral.amazon.com/reportcentral/AFNShipmentReport/1",
            button="Request .csv Download",
            file_format="CSV",
            save_as="fulfillment_csv",
        ),
    ]
    return FbaPeriodHintOut(
        last_import_date=last_dt,
        days_needed=days_needed,
        option_days=option_days,
        option_label=f"Last {option_days} days",
        reports=reports,
    )


@router.post("/import/auth-check", response_model=FbaAuthCheckOut)
async def auth_check(_staff: AdminOrSalesUser):
    """Launch the persistent Chromium profile and report whether it's logged in."""
    if runner._is_active(runner.get_state()):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An import is running — the browser profile is in use.",
        )
    scraper = runner._scraper_factory(
        profile_path=settings.fba_chrome_profile_path,
        headless=settings.fba_scraper_headless,
        host_resolver_rules=settings.fba_scraper_host_resolver_rules,
    )
    _detail = {
        "logged_in": None,
        "signed_out": "Seller Central is signed out — refresh the profile (Docs/FBA_Import_Handoff.md).",
        "unverified": (
            "Couldn't reach Seller Central to verify — the import will still try to "
            "scrape names and report if the session is actually dead."
        ),
    }
    try:
        await scraper.start()
        state = await asyncio.wait_for(scraper.check_auth(), timeout=90)
        return FbaAuthCheckOut(state=state, detail=_detail.get(state))
    except Exception as exc:  # noqa: BLE001
        logger.warning("FBA auth-check failed: %s", exc)
        return FbaAuthCheckOut(state="unverified", detail=f"Browser check failed: {str(exc)[:160]}")
    finally:
        try:
            await scraper.close()
        except Exception:  # noqa: BLE001
            pass
