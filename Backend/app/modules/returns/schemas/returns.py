"""
Pydantic schemas for Returns endpoints.
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.modules.orders.models import OrderPlatform
from app.modules.returns.models import ReturnNormalizedStatus


class ReturnItemDetail(BaseModel):
    id: int
    linked_order_item_id: Optional[int] = None
    external_item_id: Optional[str] = None
    external_sku: Optional[str] = None
    item_name: str
    ordered_qty: int
    returned_qty: int
    cancelled_qty: int
    refunded_amount: Decimal
    item_payload: Optional[dict] = None

    model_config = ConfigDict(from_attributes=True)


class ReturnRecordBrief(BaseModel):
    id: int
    platform: OrderPlatform
    source: str
    external_record_key: str
    external_order_id: str
    external_return_id: Optional[str] = None
    linked_order_id: Optional[int] = None
    customer_name: Optional[str] = None
    customer_email: Optional[str] = None
    ordered_at: Optional[datetime] = None
    event_at: Optional[datetime] = None
    last_source_updated_at: Optional[datetime] = None
    normalized_status: ReturnNormalizedStatus
    source_status: Optional[str] = None
    source_substatus: Optional[str] = None
    reason: Optional[str] = None
    order_total_amount: Decimal
    refunded_amount: Decimal
    currency: str
    item_count: int = 0
    returned_qty_total: int = 0
    cancelled_qty_total: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ReturnRecordDetail(ReturnRecordBrief):
    raw_payload: Optional[dict] = None
    items: list[ReturnItemDetail] = Field(default_factory=list)


class ReturnListResponse(BaseModel):
    total: int
    skip: int
    limit: int
    items: list[ReturnRecordBrief]
    summary_counts: dict[str, int] = Field(default_factory=dict)
