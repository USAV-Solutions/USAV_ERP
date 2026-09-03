"""Pydantic response/request models for the tracking scraper API."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.modules.tracking.runner import TrackingItemState, TrackingJobState


class EligibleCountOut(BaseModel):
    count: int


class TrackingItemOut(BaseModel):
    order_number: str
    tracking_number: str
    order_ids: list[int]
    result: str | None
    detail: str | None
    checked_at: datetime | None
    attempts: int
    parcelsapp_url: str
    changed_order_ids: list[int] = []

    @classmethod
    def from_state(cls, item: TrackingItemState) -> "TrackingItemOut":
        return cls(
            order_number=item.order_number,
            tracking_number=item.tracking_number,
            order_ids=item.order_ids,
            result=item.result,
            detail=item.detail,
            checked_at=item.checked_at,
            attempts=item.attempts,
            parcelsapp_url=item.parcelsapp_url,
            changed_order_ids=item.changed_order_ids,
        )


class TrackingJobOut(BaseModel):
    job_id: str | None
    status: str  # idle | running | paused_rate_limit | completed | aborted | failed
    started_at: datetime | None = None
    finished_at: datetime | None = None
    total: int = 0
    processed: int = 0
    remaining: int = 0
    counts: dict[str, int] = {}
    current: TrackingItemOut | None = None
    cooldown_until: datetime | None = None
    consecutive_rate_limited: int = 0
    auto_probe: bool = True
    auto_probe_interval_minutes: int = 15
    last_probe_result: str | None = None
    last_probe_at: datetime | None = None
    cancel_requested: bool = False
    message: str | None = None
    last_error: str | None = None
    # Distinct order ids whose shipping_status flipped this run → need a Zoho push.
    changed_order_ids: list[int] = []
    items: list[TrackingItemOut] = []

    @classmethod
    def idle(cls) -> "TrackingJobOut":
        return cls(job_id=None, status="idle")

    @classmethod
    def from_state(cls, job: TrackingJobState) -> "TrackingJobOut":
        return cls(
            job_id=job.job_id,
            status=job.status,
            started_at=job.started_at,
            finished_at=job.finished_at,
            total=job.total,
            processed=job.processed,
            remaining=job.remaining,
            counts=job.counts,
            current=TrackingItemOut.from_state(job.current) if job.current else None,
            cooldown_until=job.cooldown_until,
            consecutive_rate_limited=job.consecutive_rate_limited,
            auto_probe=job.auto_probe,
            auto_probe_interval_minutes=job.auto_probe_interval_minutes,
            last_probe_result=job.last_probe_result,
            last_probe_at=job.last_probe_at,
            cancel_requested=job.cancel_requested,
            message=job.message,
            last_error=job.last_error,
            changed_order_ids=job.changed_order_ids,
            items=[TrackingItemOut.from_state(it) for it in job.items],
        )


class ProbeResultOut(BaseModel):
    result: str | None  # OK | RATE_LIMITED | ERROR
    job: TrackingJobOut


class AutoProbeIn(BaseModel):
    enabled: bool
