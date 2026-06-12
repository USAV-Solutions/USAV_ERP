"""
Pydantic schemas for Returns sync endpoints.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.modules.orders.models import IntegrationSyncStatus


class ReturnSyncStateResponse(BaseModel):
    id: int
    platform_name: str
    last_successful_sync: Optional[datetime] = None
    current_status: IntegrationSyncStatus
    last_error_message: Optional[str] = None
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ReturnSyncRequest(BaseModel):
    platform: Optional[str] = Field(default=None, description="Platform key. Omit to sync all configured platforms.")


class ReturnSyncRangeRequest(BaseModel):
    platform: Optional[str] = Field(default=None, description="Platform key. Omit to sync all configured platforms.")
    since: datetime
    until: datetime


class ReturnSyncResponse(BaseModel):
    platform: str
    new_records: int = 0
    updated_records: int = 0
    new_items: int = 0
    linked_orders: int = 0
    linked_items: int = 0
    skipped_duplicates: int = 0
    errors: list[str] = Field(default_factory=list)
    success: bool = True


class ReturnSyncStatusResponse(BaseModel):
    platforms: list[ReturnSyncStateResponse]
    total_records: int = 0
    counts_by_status: dict[str, int] = Field(default_factory=dict)
