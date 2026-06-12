"""
Pydantic schemas for Returns sync endpoints.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.modules.orders.models import IntegrationSyncStatus
from app.modules.orders.models import OrderPlatform
from app.modules.returns.models import ReturnZohoSyncStatus


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


class ReturnZohoLineValidationResponse(BaseModel):
    return_item_id: int
    linked_order_item_id: Optional[int] = None
    quantity: int = 0
    zoho_salesorder_item_id: Optional[str] = None
    status: ReturnZohoSyncStatus
    message: Optional[str] = None


class ReturnZohoValidationResponse(BaseModel):
    record_id: int
    status: ReturnZohoSyncStatus
    blockers: list[str] = Field(default_factory=list)
    zoho_salesorder_id: Optional[str] = None
    zoho_salesreturn_id: Optional[str] = None
    zoho_salesreturn_number: Optional[str] = None
    line_items: list[ReturnZohoLineValidationResponse] = Field(default_factory=list)


class ReturnZohoSyncRangeRequest(BaseModel):
    platform: Optional[OrderPlatform] = None
    since: Optional[datetime] = None
    until: Optional[datetime] = None
    limit: int = Field(default=100, ge=1, le=500)


class ReturnZohoSyncRangeResponse(BaseModel):
    total: int = 0
    synced: int = 0
    blocked: int = 0
    failed: int = 0
    items: list[ReturnZohoValidationResponse] = Field(default_factory=list)


class ReturnZohoSyncStatusResponse(BaseModel):
    total_records: int = 0
    counts_by_status: dict[str, int] = Field(default_factory=dict)
