"""Pydantic request/response models for the FBA import API."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.modules.fba.runner import BuyerNameItemState, FbaImportJobState


class BuyerNameItemOut(BaseModel):
    order_id: str
    result: str | None
    buyer_name: str | None
    detail: str | None
    attempts: int
    checked_at: datetime | None

    @classmethod
    def from_state(cls, it: BuyerNameItemState) -> "BuyerNameItemOut":
        return cls(
            order_id=it.order_id,
            result=it.result,
            buyer_name=it.buyer_name,
            detail=it.detail,
            attempts=it.attempts,
            checked_at=it.checked_at,
        )


class FbaImportJobOut(BaseModel):
    job_id: str | None
    status: str  # idle | running | completed | completed_with_warnings | aborted | failed
    phase: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    all_order_rows: int = 0
    fba_order_rows: int = 0
    shipment_rows: int = 0
    merged_rows: int = 0
    total_names: int = 0
    scraped_names: int = 0
    counts: dict[str, int] = {}
    orders_created: int = 0
    orders_updated: int = 0
    items_created: int = 0
    warnings: list[str] = []
    message: str | None = None
    last_error: str | None = None
    cancel_requested: bool = False
    items: list[BuyerNameItemOut] = []

    @classmethod
    def idle(cls) -> "FbaImportJobOut":
        return cls(job_id=None, status="idle")

    @classmethod
    def from_state(cls, job: FbaImportJobState) -> "FbaImportJobOut":
        return cls(
            job_id=job.job_id,
            status=job.status,
            phase=job.phase,
            started_at=job.started_at,
            finished_at=job.finished_at,
            all_order_rows=job.all_order_rows,
            fba_order_rows=job.fba_order_rows,
            shipment_rows=job.shipment_rows,
            merged_rows=job.merged_rows,
            total_names=job.total_names,
            scraped_names=job.scraped_names,
            counts=job.counts,
            orders_created=job.orders_created,
            orders_updated=job.orders_updated,
            items_created=job.items_created,
            warnings=job.warnings,
            message=job.message,
            last_error=job.last_error,
            cancel_requested=job.cancel_requested,
            items=[BuyerNameItemOut.from_state(it) for it in job.items],
        )


class FbaReportHint(BaseModel):
    name: str
    url: str
    button: str
    file_format: str
    save_as: str


class FbaPeriodHintOut(BaseModel):
    last_import_date: datetime | None
    days_needed: int
    option_days: int
    option_label: str  # e.g. "Last 15 days"
    reports: list[FbaReportHint]


class FbaAuthCheckOut(BaseModel):
    state: str  # logged_in | signed_out | unverified
    detail: str | None = None
