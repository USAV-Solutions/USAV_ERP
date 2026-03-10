"""Pydantic schemas for purchasing module."""
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models import PurchaseDeliverStatus, PurchaseOrderItemStatus


class VendorBase(BaseModel):
    name: str = Field(..., max_length=200)
    email: Optional[str] = Field(None, max_length=200)
    phone: Optional[str] = Field(None, max_length=50)
    address: Optional[str] = None
    is_active: bool = True


class VendorCreate(VendorBase):
    pass


class VendorUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
    email: Optional[str] = Field(None, max_length=200)
    phone: Optional[str] = Field(None, max_length=50)
    address: Optional[str] = None
    is_active: Optional[bool] = None


class VendorResponse(VendorBase):
    id: int
    zoho_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PurchaseOrderItemBase(BaseModel):
    variant_id: Optional[int] = None
    external_item_name: str = Field(..., max_length=255)
    quantity: int = Field(..., gt=0)
    unit_price: Decimal = Field(..., ge=0)
    total_price: Decimal = Field(..., ge=0)
    status: PurchaseOrderItemStatus = PurchaseOrderItemStatus.UNMATCHED


class PurchaseOrderItemCreate(PurchaseOrderItemBase):
    pass


class PurchaseOrderItemUpdate(BaseModel):
    variant_id: Optional[int] = None
    external_item_name: Optional[str] = Field(None, max_length=255)
    quantity: Optional[int] = Field(None, gt=0)
    unit_price: Optional[Decimal] = Field(None, ge=0)
    total_price: Optional[Decimal] = Field(None, ge=0)
    status: Optional[PurchaseOrderItemStatus] = None


class PurchaseOrderItemResponse(PurchaseOrderItemBase):
    id: int
    purchase_order_id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PurchaseOrderBase(BaseModel):
    po_number: str = Field(..., max_length=100)
    vendor_id: int
    deliver_status: PurchaseDeliverStatus = PurchaseDeliverStatus.CREATED
    order_date: date
    expected_delivery_date: Optional[date] = None
    total_amount: Decimal = Field(..., ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    notes: Optional[str] = None


class PurchaseOrderCreate(PurchaseOrderBase):
    items: list[PurchaseOrderItemCreate] = Field(default_factory=list)


class PurchaseOrderUpdate(BaseModel):
    po_number: Optional[str] = Field(None, max_length=100)
    vendor_id: Optional[int] = None
    deliver_status: Optional[PurchaseDeliverStatus] = None
    order_date: Optional[date] = None
    expected_delivery_date: Optional[date] = None
    total_amount: Optional[Decimal] = Field(None, ge=0)
    currency: Optional[str] = Field(None, min_length=3, max_length=3)
    notes: Optional[str] = None


class PurchaseOrderResponse(PurchaseOrderBase):
    id: int
    zoho_id: Optional[str] = None
    vendor: Optional[VendorResponse] = None
    items: list[PurchaseOrderItemResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PurchaseOrderItemMatchRequest(BaseModel):
    variant_id: int = Field(..., gt=0)


class ItemReceipt(BaseModel):
    purchase_order_item_id: int = Field(..., gt=0)
    quantity_received: int = Field(..., gt=0)
    serial_numbers: list[str] = Field(default_factory=list)
    location_code: Optional[str] = Field(None, max_length=50)


class PurchaseOrderReceiveRequest(BaseModel):
    items: list[ItemReceipt] = Field(default_factory=list)


class PurchaseOrderReceiveResponse(BaseModel):
    purchase_order_id: int
    created_inventory_item_ids: list[int] = Field(default_factory=list)
    deliver_status: PurchaseDeliverStatus


class ZohoPurchaseImportResponse(BaseModel):
    vendors_created: int = 0
    vendors_updated: int = 0
    purchase_orders_created: int = 0
    purchase_orders_updated: int = 0
    purchase_order_items_replaced: int = 0
    source_vendors_seen: int = 0
    source_purchase_orders_seen: int = 0
