"""
Pydantic schemas for integration-state / sync endpoints.
"""
from enum import Enum
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.modules.orders.models import IntegrationSyncStatus


class IntegrationStateResponse(BaseModel):
    """Public representation of a platform's sync state."""
    id: int
    platform_name: str
    last_successful_sync: Optional[datetime] = None
    current_status: IntegrationSyncStatus
    last_error_message: Optional[str] = None
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SyncRequest(BaseModel):
    """
    Trigger a sync for one or all platforms.

    If ``platform`` is omitted, all configured platforms are synced.
    """
    platform: Optional[str] = Field(
        default=None,
        description="Platform key (e.g. 'AMAZON'). Omit to sync all.",
    )


class SyncRangeRequest(BaseModel):
    """
    Admin-only: sync orders within a specific date range.

    Bypasses the normal sync-lock / last-sync anchor – fetches orders
    whose ``ordered_at`` falls between ``since`` and ``until``.
    Duplicates are still safely skipped.
    """
    platform: Optional[str] = Field(
        default=None,
        description="Platform key (e.g. 'AMAZON'). Omit to sync all.",
    )
    since: datetime = Field(
        ...,
        description="Start of the fetch window (UTC).",
    )
    until: datetime = Field(
        ...,
        description="End of the fetch window (UTC).",
    )


class SyncResponse(BaseModel):
    """Result summary returned after a sync run."""
    platform: str
    new_orders: int = Field(default=0, description="Orders inserted (excluding duplicates).")
    new_items: int = Field(default=0, description="Line items created.")
    auto_matched: int = Field(default=0, description="Items auto-linked via PLATFORM_LISTING.")
    skipped_duplicates: int = Field(default=0, description="Orders already in the database.")
    errors: list[str] = Field(default_factory=list)
    success: bool = True


class SyncStatusResponse(BaseModel):
    """Overview of all platform sync states + dashboard counters."""
    platforms: list[IntegrationStateResponse]
    total_orders: int = 0
    total_unmatched_items: int = 0
    total_matched_items: int = 0


class SalesImportApiSource(str, Enum):
    ECWID = "ECWID"
    EBAY_MEKONG = "EBAY_MEKONG"
    EBAY_USAV = "EBAY_USAV"
    EBAY_DRAGON = "EBAY_DRAGON"
    WALMART = "WALMART"


class SalesImportFileSource(str, Enum):
    CSV_GENERIC = "CSV_GENERIC"
    SHIPSTATION_CUSTOMER_CSV = "SHIPSTATION_CUSTOMER_CSV"


class SalesImportApiRequest(BaseModel):
    source: SalesImportApiSource
    since: datetime = Field(..., description="Start of import window (UTC).")
    until: datetime = Field(..., description="End of import window (UTC).")


class SalesImportFileResponse(BaseModel):
    source: SalesImportFileSource
    source_rows_seen: int = 0
    source_rows_skipped: int = 0
    customers_created: int = 0
    customers_updated: int = 0
    new_orders: int = 0
    new_items: int = 0
    auto_matched: int = 0
    skipped_duplicates: int = 0
    success: bool = True
    errors: list[str] = Field(default_factory=list)
