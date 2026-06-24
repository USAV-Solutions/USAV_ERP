"""
Zoho Sales Return validation and outbound sync for ERP return records.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.integrations.zoho.client import ZohoClient
from app.modules.orders.models import Order, OrderItem, OrderPlatform
from app.modules.returns.models import (
    ReturnItem,
    ReturnNormalizedStatus,
    ReturnRecord,
    ReturnZohoSyncStatus,
)


CANCEL_STATUSES = {
    ReturnNormalizedStatus.CANCELLED,
    ReturnNormalizedStatus.PARTIALLY_CANCELLED,
}


@dataclass
class ZohoReturnLineValidation:
    return_item_id: int
    linked_order_item_id: Optional[int]
    quantity: int
    zoho_item_id: Optional[str]
    zoho_salesorder_item_id: Optional[str]
    status: ReturnZohoSyncStatus
    message: Optional[str] = None


@dataclass
class ZohoReturnValidation:
    record_id: int
    status: ReturnZohoSyncStatus
    blockers: list[str] = field(default_factory=list)
    zoho_salesorder_id: Optional[str] = None
    zoho_salesreturn_id: Optional[str] = None
    zoho_salesreturn_number: Optional[str] = None
    line_items: list[ZohoReturnLineValidation] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return self.status == ReturnZohoSyncStatus.READY_TO_SYNC


class ZohoReturnSyncService:
    def __init__(self, session: AsyncSession, zoho_client: Optional[ZohoClient] = None):
        self.session = session
        self.zoho_client = zoho_client or ZohoClient()

    async def validate_return_for_zoho(self, record_id: int) -> ZohoReturnValidation:
        record = await self._get_record(record_id)
        if record is None:
            raise LookupError(f"Return record {record_id} not found.")

        if self._is_cancel_record(record):
            validation = await self._validate_cancel_record(record)
        else:
            validation = await self._validate_record(record)
        self._apply_validation_status(record, validation)
        await self.session.commit()
        return validation

    async def sync_return_to_zoho(self, record_id: int) -> ZohoReturnValidation:
        record = await self._get_record(record_id)
        if record is None:
            raise LookupError(f"Return record {record_id} not found.")

        if self._is_cancel_record(record):
            return await self._sync_cancel_to_zoho(record)

        validation = await self._validate_record(record)
        if validation.status == ReturnZohoSyncStatus.ALREADY_SYNCED:
            self._apply_validation_status(record, validation)
            await self.session.commit()
            return validation
        if not validation.ready:
            self._apply_validation_status(record, validation)
            await self.session.commit()
            return validation

        payload = self.build_sales_return_payload(record, validation)
        try:
            await self._ensure_return_items_are_returnable(payload)
            sales_return = await self.zoho_client.create_sales_return(payload)
            salesreturn_id = str(
                sales_return.get("salesreturn_id")
                or sales_return.get("sales_return_id")
                or sales_return.get("return_id")
                or ""
            ).strip()
            if not salesreturn_id:
                raise ValueError("Zoho Sales Return creation succeeded without a salesreturn_id.")

            record.zoho_salesreturn_id = salesreturn_id
            record.zoho_salesreturn_number = str(
                sales_return.get("salesreturn_number")
                or sales_return.get("sales_return_number")
                or sales_return.get("return_number")
                or ""
            ).strip() or None
            record.zoho_sync_status = ReturnZohoSyncStatus.SYNCED
            record.zoho_sync_error = None
            record.zoho_synced_at = datetime.now(timezone.utc)
            await self.session.commit()

            validation.status = ReturnZohoSyncStatus.SYNCED
            validation.zoho_salesreturn_id = record.zoho_salesreturn_id
            validation.zoho_salesreturn_number = record.zoho_salesreturn_number
            return validation
        except Exception as exc:
            record.zoho_sync_status = ReturnZohoSyncStatus.ERROR
            record.zoho_sync_error = str(exc)
            await self.session.commit()
            validation.status = ReturnZohoSyncStatus.ERROR
            validation.blockers = [str(exc)]
            return validation

    async def _sync_cancel_to_zoho(self, record: ReturnRecord) -> ZohoReturnValidation:
        validation = await self._validate_cancel_record(record)
        if validation.status == ReturnZohoSyncStatus.ALREADY_SYNCED:
            self._apply_validation_status(record, validation)
            await self.session.commit()
            return validation
        if not validation.ready:
            self._apply_validation_status(record, validation)
            await self.session.commit()
            return validation

        try:
            salesorder_id = str(validation.zoho_salesorder_id or "")
            salesorder = await self.zoho_client.get_salesorder(salesorder_id)
            if self._cancels_entire_salesorder(salesorder, validation):
                await self.zoho_client.void_salesorder(salesorder_id)
            else:
                payload = self.build_salesorder_cancel_payload(salesorder, validation)
                await self.zoho_client.update_salesorder(salesorder_id, payload)

            record.zoho_sync_status = ReturnZohoSyncStatus.SYNCED
            record.zoho_sync_error = None
            record.zoho_synced_at = datetime.now(timezone.utc)
            await self.session.commit()
            validation.status = ReturnZohoSyncStatus.SYNCED
            return validation
        except Exception as exc:
            record.zoho_sync_status = ReturnZohoSyncStatus.ERROR
            record.zoho_sync_error = str(exc)
            await self.session.commit()
            validation.status = ReturnZohoSyncStatus.ERROR
            validation.blockers = [str(exc)]
            return validation

    async def sync_eligible_returns_to_zoho(
        self,
        *,
        platform: Optional[OrderPlatform] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        limit: int = 100,
    ) -> list[ZohoReturnValidation]:
        stmt = (
            select(ReturnRecord.id)
            .where(ReturnRecord.zoho_salesreturn_id.is_(None))
            .where(ReturnRecord.zoho_sync_status != ReturnZohoSyncStatus.SYNCED)
            .order_by(ReturnRecord.event_at.asc().nulls_last(), ReturnRecord.id.asc())
            .limit(limit)
        )
        if platform is not None:
            stmt = stmt.where(ReturnRecord.platform == platform)
        if since is not None:
            stmt = stmt.where(ReturnRecord.event_at >= since)
        if until is not None:
            stmt = stmt.where(ReturnRecord.event_at <= until)

        ids = (await self.session.execute(stmt)).scalars().all()
        results: list[ZohoReturnValidation] = []
        for record_id in ids:
            results.append(await self.sync_return_to_zoho(int(record_id)))
        return results

    async def count_by_zoho_status(self) -> dict[str, int]:
        stmt = select(ReturnRecord.zoho_sync_status, func.count()).group_by(ReturnRecord.zoho_sync_status)
        rows = (await self.session.execute(stmt)).all()
        return {
            status.value if hasattr(status, "value") else str(status): count
            for status, count in rows
        }

    async def count_returns(self) -> int:
        return int((await self.session.execute(select(func.count(ReturnRecord.id)))).scalar_one())

    async def _get_record(self, record_id: int) -> Optional[ReturnRecord]:
        stmt = (
            select(ReturnRecord)
            .options(
                selectinload(ReturnRecord.linked_order)
                .selectinload(Order.items)
                .selectinload(OrderItem.variant),
                selectinload(ReturnRecord.items)
                .selectinload(ReturnItem.linked_order_item)
                .selectinload(OrderItem.variant),
            )
            .where(ReturnRecord.id == record_id)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _validate_cancel_record(self, record: ReturnRecord) -> ZohoReturnValidation:
        if record.zoho_sync_status == ReturnZohoSyncStatus.SYNCED:
            return ZohoReturnValidation(record_id=record.id, status=ReturnZohoSyncStatus.ALREADY_SYNCED)

        order = record.linked_order
        if order is None:
            return ZohoReturnValidation(
                record_id=record.id,
                status=ReturnZohoSyncStatus.MISSING_LOCAL_ORDER,
                blockers=["Cancellation record is not linked to a local order."],
            )

        zoho_salesorder_id = await self._resolve_zoho_salesorder_id(order)
        if not zoho_salesorder_id:
            return ZohoReturnValidation(
                record_id=record.id,
                status=ReturnZohoSyncStatus.MISSING_ZOHO_ORDER,
                blockers=["Linked order has no Zoho Sales Order ID and could not be found in Zoho."],
            )

        salesorder = await self.zoho_client.get_salesorder(zoho_salesorder_id)
        salesorder_lines = salesorder.get("line_items") or []
        validation = ZohoReturnValidation(
            record_id=record.id,
            status=ReturnZohoSyncStatus.READY_TO_SYNC,
            zoho_salesorder_id=zoho_salesorder_id,
        )

        for item in record.items or []:
            line_validation = await self._validate_cancel_item(record, order, item, salesorder_lines)
            validation.line_items.append(line_validation)
            if line_validation.status != ReturnZohoSyncStatus.READY_TO_SYNC and line_validation.message:
                validation.blockers.append(line_validation.message)

        if not validation.line_items:
            validation.status = ReturnZohoSyncStatus.MISSING_LINE_ITEM_MAPPING
            validation.blockers.append("Cancellation record has no line items to sync.")
        elif any(item.status == ReturnZohoSyncStatus.QUANTITY_CONFLICT for item in validation.line_items):
            validation.status = ReturnZohoSyncStatus.QUANTITY_CONFLICT
        elif any(item.status == ReturnZohoSyncStatus.MISSING_LINE_ITEM_MAPPING for item in validation.line_items):
            validation.status = ReturnZohoSyncStatus.MISSING_LINE_ITEM_MAPPING

        return validation

    async def _validate_record(self, record: ReturnRecord) -> ZohoReturnValidation:
        if record.zoho_salesreturn_id:
            return ZohoReturnValidation(
                record_id=record.id,
                status=ReturnZohoSyncStatus.ALREADY_SYNCED,
                zoho_salesreturn_id=record.zoho_salesreturn_id,
                zoho_salesreturn_number=record.zoho_salesreturn_number,
            )

        order = record.linked_order
        if order is None:
            return ZohoReturnValidation(
                record_id=record.id,
                status=ReturnZohoSyncStatus.MISSING_LOCAL_ORDER,
                blockers=["Return record is not linked to a local order."],
            )

        zoho_salesorder_id = await self._resolve_zoho_salesorder_id(order)
        if not zoho_salesorder_id:
            return ZohoReturnValidation(
                record_id=record.id,
                status=ReturnZohoSyncStatus.MISSING_ZOHO_ORDER,
                blockers=["Linked order has no Zoho Sales Order ID and could not be found in Zoho."],
            )

        salesorder = await self.zoho_client.get_salesorder(zoho_salesorder_id)
        salesorder_lines = salesorder.get("line_items") or []
        validation = ZohoReturnValidation(
            record_id=record.id,
            status=ReturnZohoSyncStatus.READY_TO_SYNC,
            zoho_salesorder_id=zoho_salesorder_id,
        )

        for item in record.items or []:
            line_validation = await self._validate_item(record, order, item, salesorder_lines)
            validation.line_items.append(line_validation)
            if line_validation.status != ReturnZohoSyncStatus.READY_TO_SYNC and line_validation.message:
                validation.blockers.append(line_validation.message)

        if not validation.line_items:
            validation.status = ReturnZohoSyncStatus.MISSING_LINE_ITEM_MAPPING
            validation.blockers.append("Return record has no line items to sync.")
        elif any(item.status == ReturnZohoSyncStatus.QUANTITY_CONFLICT for item in validation.line_items):
            validation.status = ReturnZohoSyncStatus.QUANTITY_CONFLICT
        elif any(item.status == ReturnZohoSyncStatus.MISSING_LINE_ITEM_MAPPING for item in validation.line_items):
            validation.status = ReturnZohoSyncStatus.MISSING_LINE_ITEM_MAPPING

        return validation

    async def _resolve_zoho_salesorder_id(self, order: Order) -> Optional[str]:
        if order.zoho_id:
            return str(order.zoho_id)

        for reference in (order.external_order_number, order.external_order_id):
            if not reference:
                continue
            match = await self.zoho_client.search_salesorder_by_reference(str(reference))
            if match:
                order.zoho_id = str(match.get("salesorder_id", "")) or None
                return order.zoho_id
        return None

    async def _validate_item(
        self,
        record: ReturnRecord,
        order: Order,
        item: ReturnItem,
        salesorder_lines: list[dict[str, Any]],
    ) -> ZohoReturnLineValidation:
        quantity = self._return_quantity(item)
        order_item = item.linked_order_item or self._match_local_order_item(order, item)
        if order_item and not item.linked_order_item_id:
            item.linked_order_item_id = order_item.id

        if order_item is None:
            return ZohoReturnLineValidation(
                return_item_id=item.id,
                linked_order_item_id=None,
                quantity=quantity,
                zoho_item_id=None,
                zoho_salesorder_item_id=None,
                status=ReturnZohoSyncStatus.MISSING_LINE_ITEM_MAPPING,
                message=f"Return item {item.id} is not linked to a local order item.",
            )

        if quantity <= 0:
            return ZohoReturnLineValidation(
                return_item_id=item.id,
                linked_order_item_id=order_item.id,
                quantity=quantity,
                zoho_item_id=None,
                zoho_salesorder_item_id=None,
                status=ReturnZohoSyncStatus.QUANTITY_CONFLICT,
                message=f"Return item {item.id} has no returned or cancelled quantity.",
            )

        already_synced_qty = await self._already_synced_quantity(record.id, order_item.id)
        available_qty = int(order_item.quantity or 0) - already_synced_qty
        if quantity > available_qty:
            return ZohoReturnLineValidation(
                return_item_id=item.id,
                linked_order_item_id=order_item.id,
                quantity=quantity,
                zoho_item_id=None,
                zoho_salesorder_item_id=None,
                status=ReturnZohoSyncStatus.QUANTITY_CONFLICT,
                message=(
                    f"Return item {item.id} quantity {quantity} exceeds available "
                    f"order quantity {available_qty}."
                ),
            )

        zoho_line = self._match_zoho_salesorder_line(order_item, salesorder_lines)
        zoho_line_id = self._zoho_salesorder_item_id(zoho_line) if zoho_line else None
        zoho_item_id = self._zoho_item_id(zoho_line) if zoho_line else None
        if not zoho_line_id or not zoho_item_id:
            return ZohoReturnLineValidation(
                return_item_id=item.id,
                linked_order_item_id=order_item.id,
                quantity=quantity,
                zoho_item_id=None,
                zoho_salesorder_item_id=None,
                status=ReturnZohoSyncStatus.MISSING_LINE_ITEM_MAPPING,
                message=f"Order item {order_item.id} has no matching Zoho Sales Order line item with item_id.",
            )

        returnable_qty = self._zoho_returnable_quantity(zoho_line)
        if quantity > returnable_qty:
            return ZohoReturnLineValidation(
                return_item_id=item.id,
                linked_order_item_id=order_item.id,
                quantity=quantity,
                zoho_item_id=zoho_item_id,
                zoho_salesorder_item_id=zoho_line_id,
                status=ReturnZohoSyncStatus.QUANTITY_CONFLICT,
                message=(
                    f"Return item {item.id} quantity {quantity} exceeds Zoho shipped quantity "
                    f"available to return {returnable_qty}."
                ),
            )

        return ZohoReturnLineValidation(
            return_item_id=item.id,
            linked_order_item_id=order_item.id,
            quantity=quantity,
            zoho_item_id=zoho_item_id,
            zoho_salesorder_item_id=zoho_line_id,
            status=ReturnZohoSyncStatus.READY_TO_SYNC,
        )

    async def _validate_cancel_item(
        self,
        record: ReturnRecord,
        order: Order,
        item: ReturnItem,
        salesorder_lines: list[dict[str, Any]],
    ) -> ZohoReturnLineValidation:
        quantity = int(item.cancelled_qty or 0)
        order_item = item.linked_order_item or self._match_local_order_item(order, item)
        if order_item and not item.linked_order_item_id:
            item.linked_order_item_id = order_item.id

        if order_item is None:
            return ZohoReturnLineValidation(
                return_item_id=item.id,
                linked_order_item_id=None,
                quantity=quantity,
                zoho_item_id=None,
                zoho_salesorder_item_id=None,
                status=ReturnZohoSyncStatus.MISSING_LINE_ITEM_MAPPING,
                message=f"Cancellation item {item.id} is not linked to a local order item.",
            )

        if quantity <= 0:
            return ZohoReturnLineValidation(
                return_item_id=item.id,
                linked_order_item_id=order_item.id,
                quantity=quantity,
                zoho_item_id=None,
                zoho_salesorder_item_id=None,
                status=ReturnZohoSyncStatus.QUANTITY_CONFLICT,
                message=f"Cancellation item {item.id} has no cancelled quantity.",
            )

        already_synced_qty = await self._already_synced_quantity(record.id, order_item.id)
        available_qty = int(order_item.quantity or 0) - already_synced_qty
        if quantity > available_qty:
            return ZohoReturnLineValidation(
                return_item_id=item.id,
                linked_order_item_id=order_item.id,
                quantity=quantity,
                zoho_item_id=None,
                zoho_salesorder_item_id=None,
                status=ReturnZohoSyncStatus.QUANTITY_CONFLICT,
                message=(
                    f"Cancellation item {item.id} quantity {quantity} exceeds available "
                    f"order quantity {available_qty}."
                ),
            )

        zoho_line = self._match_zoho_salesorder_line(order_item, salesorder_lines)
        zoho_line_id = self._zoho_salesorder_item_id(zoho_line) if zoho_line else None
        zoho_item_id = self._zoho_item_id(zoho_line) if zoho_line else None
        if not zoho_line_id or not zoho_item_id:
            return ZohoReturnLineValidation(
                return_item_id=item.id,
                linked_order_item_id=order_item.id,
                quantity=quantity,
                zoho_item_id=None,
                zoho_salesorder_item_id=None,
                status=ReturnZohoSyncStatus.MISSING_LINE_ITEM_MAPPING,
                message=f"Order item {order_item.id} has no matching Zoho Sales Order line item with item_id.",
            )

        cancelable_qty = self._zoho_cancelable_quantity(zoho_line)
        if quantity > cancelable_qty:
            return ZohoReturnLineValidation(
                return_item_id=item.id,
                linked_order_item_id=order_item.id,
                quantity=quantity,
                zoho_item_id=zoho_item_id,
                zoho_salesorder_item_id=zoho_line_id,
                status=ReturnZohoSyncStatus.QUANTITY_CONFLICT,
                message=(
                    f"Cancellation item {item.id} quantity {quantity} exceeds Zoho unfulfilled "
                    f"quantity available to cancel {cancelable_qty}."
                ),
            )

        return ZohoReturnLineValidation(
            return_item_id=item.id,
            linked_order_item_id=order_item.id,
            quantity=quantity,
            zoho_item_id=zoho_item_id,
            zoho_salesorder_item_id=zoho_line_id,
            status=ReturnZohoSyncStatus.READY_TO_SYNC,
        )

    def build_sales_return_payload(self, record: ReturnRecord, validation: ZohoReturnValidation) -> dict[str, Any]:
        line_items = [
            {
                "item_id": item.zoho_item_id,
                "salesorder_item_id": item.zoho_salesorder_item_id,
                "quantity": item.quantity,
            }
            for item in validation.line_items
            if item.status == ReturnZohoSyncStatus.READY_TO_SYNC and item.zoho_salesorder_item_id and item.zoho_item_id
        ]
        if not validation.zoho_salesorder_id or not line_items:
            raise ValueError("Return record is not ready for Zoho Sales Return payload creation.")

        event_at = record.event_at or datetime.now(timezone.utc)
        reference_number = record.external_return_id or record.external_record_key
        notes = (
            f"ERP return {record.id}; platform={record.platform.value}; "
            f"external_order_id={record.external_order_id}; status={record.normalized_status.value}"
        )
        payload: dict[str, Any] = {
            "salesorder_id": validation.zoho_salesorder_id,
            "date": event_at.strftime("%Y-%m-%d"),
            "reference_number": str(reference_number),
            "line_items": line_items,
            "notes": notes,
        }
        if record.reason:
            payload["reason"] = record.reason
        return payload

    def build_salesorder_cancel_payload(
        self,
        salesorder: dict[str, Any],
        validation: ZohoReturnValidation,
    ) -> dict[str, Any]:
        cancel_by_line_id = {
            item.zoho_salesorder_item_id: item.quantity
            for item in validation.line_items
            if item.status == ReturnZohoSyncStatus.READY_TO_SYNC and item.zoho_salesorder_item_id
        }
        line_items: list[dict[str, Any]] = []
        for line in salesorder.get("line_items") or []:
            line_id = self._zoho_salesorder_item_id(line)
            quantity = self._zoho_line_quantity(line)
            cancel_qty = cancel_by_line_id.get(line_id, 0)
            new_qty = quantity - cancel_qty
            if new_qty <= 0:
                continue
            line_items.append(
                {
                    "line_item_id": line_id,
                    "item_id": self._zoho_item_id(line),
                    "quantity": new_qty,
                }
            )
        if not line_items:
            raise ValueError("Cancellation removes all lines; void the Zoho Sales Order instead.")
        return {"line_items": line_items}

    async def _ensure_return_items_are_returnable(self, payload: dict[str, Any]) -> None:
        item_ids = {
            str(line.get("item_id") or "").strip()
            for line in payload.get("line_items", [])
            if str(line.get("item_id") or "").strip()
        }
        for item_id in sorted(item_ids):
            zoho_item = await self.zoho_client.get_item(item_id)
            if zoho_item.get("is_returnable") is False:
                await self.zoho_client.update_item(item_id, {"is_returnable": True})

    def _apply_validation_status(self, record: ReturnRecord, validation: ZohoReturnValidation) -> None:
        if validation.status == ReturnZohoSyncStatus.ALREADY_SYNCED:
            record.zoho_sync_status = ReturnZohoSyncStatus.SYNCED
            record.zoho_sync_error = None
            return
        record.zoho_sync_status = validation.status
        record.zoho_sync_error = "; ".join(validation.blockers) or None

    def _return_quantity(self, item: ReturnItem) -> int:
        returned_qty = int(item.returned_qty or 0)
        return returned_qty

    def _is_cancel_record(self, record: ReturnRecord) -> bool:
        return record.normalized_status in CANCEL_STATUSES

    def _match_local_order_item(self, order: Order, item: ReturnItem) -> Optional[OrderItem]:
        order_items = order.items or []
        if item.external_item_id:
            match = next(
                (row for row in order_items if str(row.external_item_id or "") == str(item.external_item_id)),
                None,
            )
            if match:
                return match
        if item.external_sku:
            sku = str(item.external_sku).strip().lower()
            match = next((row for row in order_items if str(row.external_sku or "").strip().lower() == sku), None)
            if match:
                return match
        item_name = str(item.item_name or "").strip().lower()
        if item_name:
            return next((row for row in order_items if str(row.item_name or "").strip().lower() == item_name), None)
        return None

    def _match_zoho_salesorder_line(
        self,
        order_item: OrderItem,
        salesorder_lines: list[dict[str, Any]],
    ) -> Optional[dict[str, Any]]:
        variant = getattr(order_item, "variant", None)
        if variant and getattr(variant, "zoho_item_id", None):
            item_id = str(variant.zoho_item_id)
            match = next((line for line in salesorder_lines if str(line.get("item_id", "")) == item_id), None)
            if match:
                return match

        if order_item.external_sku:
            sku = str(order_item.external_sku).strip().lower()
            match = next((line for line in salesorder_lines if str(line.get("sku", "")).strip().lower() == sku), None)
            if match:
                return match

        item_name = str(order_item.item_name or "").strip().lower()
        if item_name:
            return next((line for line in salesorder_lines if str(line.get("name", "")).strip().lower() == item_name), None)
        return None

    def _zoho_salesorder_item_id(self, zoho_line: Optional[dict[str, Any]]) -> Optional[str]:
        if not zoho_line:
            return None
        return str(
            zoho_line.get("salesorder_item_id")
            or zoho_line.get("line_item_id")
            or ""
        ).strip() or None

    def _zoho_item_id(self, zoho_line: Optional[dict[str, Any]]) -> Optional[str]:
        if not zoho_line:
            return None
        return str(zoho_line.get("item_id") or "").strip() or None

    def _zoho_returnable_quantity(self, zoho_line: Optional[dict[str, Any]]) -> int:
        if not zoho_line:
            return 0
        try:
            shipped_qty = int(Decimal(str(zoho_line.get("quantity_shipped") or 0)))
            returned_qty = int(Decimal(str(zoho_line.get("quantity_returned") or 0)))
        except Exception:
            return 0
        return max(shipped_qty - returned_qty, 0)

    def _zoho_cancelable_quantity(self, zoho_line: Optional[dict[str, Any]]) -> int:
        if not zoho_line:
            return 0
        quantity = self._zoho_line_quantity(zoho_line)
        fulfilled_qty = max(
            self._zoho_int(zoho_line.get("quantity_packed")),
            self._zoho_int(zoho_line.get("quantity_shipped")),
            self._zoho_int(zoho_line.get("quantity_invoiced")),
        )
        return max(quantity - fulfilled_qty, 0)

    def _cancels_entire_salesorder(self, salesorder: dict[str, Any], validation: ZohoReturnValidation) -> bool:
        cancel_by_line_id = {
            item.zoho_salesorder_item_id: item.quantity
            for item in validation.line_items
            if item.status == ReturnZohoSyncStatus.READY_TO_SYNC and item.zoho_salesorder_item_id
        }
        lines = salesorder.get("line_items") or []
        if not lines:
            return False
        for line in lines:
            line_id = self._zoho_salesorder_item_id(line)
            if cancel_by_line_id.get(line_id, 0) < self._zoho_line_quantity(line):
                return False
        return True

    def _zoho_line_quantity(self, zoho_line: Optional[dict[str, Any]]) -> int:
        return self._zoho_int((zoho_line or {}).get("quantity"))

    def _zoho_int(self, value: Any) -> int:
        try:
            return int(Decimal(str(value or 0)))
        except Exception:
            return 0

    async def _already_synced_quantity(self, record_id: int, order_item_id: int) -> int:
        qty_expr = func.coalesce(func.sum(ReturnItem.returned_qty + ReturnItem.cancelled_qty), 0)
        stmt = (
            select(qty_expr)
            .join(ReturnRecord, ReturnRecord.id == ReturnItem.return_record_id)
            .where(
                ReturnItem.linked_order_item_id == order_item_id,
                ReturnRecord.id != record_id,
                or_(
                    ReturnRecord.zoho_salesreturn_id.is_not(None),
                    ReturnRecord.zoho_sync_status == ReturnZohoSyncStatus.SYNCED,
                ),
            )
        )
        return int((await self.session.execute(stmt)).scalar_one() or 0)
