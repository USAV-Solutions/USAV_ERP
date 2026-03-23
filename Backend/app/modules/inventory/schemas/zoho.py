"""Schemas for Zoho inventory synchronization endpoints."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ZohoBulkSyncRequest(BaseModel):
    """Request payload for bulk pushing variants to Zoho Inventory."""

    include_images: bool = Field(
        default=True,
        description="Upload variant thumbnail image to Zoho item when available.",
    )
    include_composites: bool = Field(
        default=True,
        description="Create/update composite items for Bundle/Kit identities.",
    )
    force_resync: bool = Field(
        default=False,
        description="Push all active variants even if already SYNCED.",
    )
    limit: int = Field(
        default=1000,
        ge=1,
        le=5000,
        description="Maximum number of variants processed in one request.",
    )
    batch_size: int = Field(
        default=100,
        ge=1,
        le=1000,
        description="Number of variants processed per batch in bulk sync.",
    )


class ZohoSingleSyncRequest(BaseModel):
    """Request payload for syncing one variant to Zoho Inventory."""

    include_images: bool = Field(
        default=True,
        description="Upload variant thumbnail image to Zoho item when available.",
    )
    include_composites: bool = Field(
        default=True,
        description="When true, sync Bundle/Kit identities as composite items.",
    )
    force_resync: bool = Field(
        default=True,
        description="When true, allow sync regardless of current Zoho sync status.",
    )


class ZohoBulkSyncItemResult(BaseModel):
    """Per-variant sync result."""

    variant_id: int
    sku: str
    action: str
    success: bool
    zoho_sync_status: Optional[str] = None
    zoho_item_id: Optional[str] = None
    image_uploaded: bool = False
    composite_synced: bool = False
    message: Optional[str] = None


class ZohoBulkSyncResponse(BaseModel):
    """Aggregate result for bulk Zoho synchronization."""

    started_at: datetime
    finished_at: datetime
    total_processed: int
    total_success: int
    total_failed: int
    items: list[ZohoBulkSyncItemResult]


class ZohoReadinessRequest(BaseModel):
    """Request payload for Zoho readiness validation report."""

    include_images: bool = Field(
        default=True,
        description="When true, report missing thumbnail for image sync readiness.",
    )
    include_composites: bool = Field(
        default=True,
        description="When true, validate Bundle/Kit component readiness.",
    )
    only_unsynced: bool = Field(
        default=False,
        description="When true, only inspect variants in PENDING or DIRTY status.",
    )
    limit: int = Field(
        default=1000,
        ge=1,
        le=5000,
        description="Maximum number of variants evaluated in one request.",
    )


class ZohoReadinessItem(BaseModel):
    """Per-variant readiness assessment for Zoho sync."""

    variant_id: int
    sku: str
    identity_type: str
    ready: bool
    severity: str
    missing_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ZohoReadinessResponse(BaseModel):
    """Aggregate readiness report for Zoho sync."""

    total_checked: int
    ready_count: int
    blocked_count: int
    warning_only_count: int
    items: list[ZohoReadinessItem]


class ZohoSyncProgressResponse(BaseModel):
    """Current state of a background Zoho bulk sync job."""

    job_id: str
    status: str
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    total_target: int
    total_processed: int
    total_success: int
    total_failed: int
    current_sku: Optional[str] = None
    cancel_requested: bool = False
    last_error: Optional[str] = None
