"""
Return Sync Service – read-only import pipeline for return/cancel/refund data.
"""
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Optional, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.base import BasePlatformClient
from app.modules.orders.models import IntegrationSyncStatus, Order, OrderItem, OrderPlatform, OrderFulfillmentChannel, OrderStatus
from app.modules.returns.models import ReturnItem, ReturnNormalizedStatus, ReturnRecord, ReturnSyncState, ReturnZohoSyncStatus
from app.modules.returns.schemas.sync import ReturnSyncResponse
from app.repositories.orders.order_repository import OrderRepository
from app.repositories.returns.record_repository import ReturnRecordRepository
from app.repositories.returns.sync_repository import ReturnSyncStateRepository
import csv

logger = logging.getLogger(__name__)

SYNC_BUFFER_MINUTES = 10

_PLATFORM_MAP: dict[str, OrderPlatform] = {
    "AMAZON": OrderPlatform.AMAZON,
    "EBAY_MEKONG": OrderPlatform.EBAY_MEKONG,
    "EBAY_USAV": OrderPlatform.EBAY_USAV,
    "EBAY_DRAGON": OrderPlatform.EBAY_DRAGON,
    "ECWID": OrderPlatform.ECWID,
    "SHOPIFY": OrderPlatform.SHOPIFY,
    "WALMART": OrderPlatform.WALMART,
    "MANUAL": OrderPlatform.MANUAL,
}

_NON_BLOCKING_AUTH_ERROR_MARKERS = (
    "unable to obtain access token",
    "credentials not configured",
)


@dataclass
class NormalizedReturnItem:
    external_item_id: Optional[str]
    external_sku: Optional[str]
    item_name: str
    ordered_qty: int = 0
    returned_qty: int = 0
    cancelled_qty: int = 0
    refunded_amount: Decimal = Decimal("0")
    payload: Optional[dict[str, Any]] = None


@dataclass
class NormalizedReturnRecord:
    external_record_key: str
    external_order_id: str
    platform: OrderPlatform
    source: str
    normalized_status: ReturnNormalizedStatus
    fulfillment_channel: OrderFulfillmentChannel = OrderFulfillmentChannel.SELF_FULFILLED
    external_return_id: Optional[str] = None
    customer_name: Optional[str] = None
    customer_email: Optional[str] = None
    ordered_at: Optional[datetime] = None
    event_at: Optional[datetime] = None
    last_source_updated_at: Optional[datetime] = None
    source_status: Optional[str] = None
    source_substatus: Optional[str] = None
    reason: Optional[str] = None
    order_total_amount: Decimal = Decimal("0")
    refunded_amount: Decimal = Decimal("0")
    currency: str = "USD"
    raw_payload: Optional[dict[str, Any]] = None
    items: list[NormalizedReturnItem] = field(default_factory=list)


def _to_decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value or 0).replace(",", ""))
    except Exception:
        return Decimal("0")


def _normalize_text(value: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _ensure_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_datetime(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return _ensure_utc(value)
    if isinstance(value, (int, float)):
        try:
            ts = float(value)
            if ts > 10_000_000_000:
                ts /= 1000.0
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except Exception:
            return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return _ensure_utc(datetime.fromisoformat(text.replace("Z", "+00:00")))
        except ValueError:
            pass
        for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%m/%d/%Y", "%Y-%m-%d"):
            try:
                return _ensure_utc(datetime.strptime(text, fmt))
            except ValueError:
                continue
        return None
    return None


def _normalize_header(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")


def _safe_int(value: object) -> int:
    try:
        return max(int(Decimal(str(value or "0").replace(",", "").strip() or "0")), 0)
    except Exception:
        return 0


def _coerce_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _status_rank(status: ReturnNormalizedStatus) -> int:
    ranks = {
        ReturnNormalizedStatus.RETURNED: 60,
        ReturnNormalizedStatus.PARTIALLY_RETURNED: 50,
        ReturnNormalizedStatus.CANCELLED: 40,
        ReturnNormalizedStatus.PARTIALLY_CANCELLED: 30,
        ReturnNormalizedStatus.REFUNDED: 20,
        ReturnNormalizedStatus.PARTIALLY_REFUNDED: 10,
        ReturnNormalizedStatus.UNKNOWN: 0,
    }
    return ranks.get(status, 0)


class ReturnSyncService:
    def __init__(
        self,
        session: AsyncSession,
        sync_repo: ReturnSyncStateRepository,
        record_repo: ReturnRecordRepository,
        order_repo: OrderRepository,
    ):
        self.session = session
        self.sync_repo = sync_repo
        self.record_repo = record_repo
        self.order_repo = order_repo

    async def sync_platform(
        self,
        platform_name: str,
        client: BasePlatformClient,
        *,
        source: str,
    ) -> ReturnSyncResponse:
        response = ReturnSyncResponse(platform=platform_name)
        await self._ensure_sync_state(platform_name)

        locked = await self.sync_repo.acquire_sync_lock(platform_name)
        if not locked:
            state = await self.sync_repo.get_by_platform(platform_name)
            state_error = (state.last_error_message or "").lower() if state else ""
            if state and state.current_status == IntegrationSyncStatus.ERROR and any(
                marker in state_error for marker in _NON_BLOCKING_AUTH_ERROR_MARKERS
            ):
                await self.sync_repo.reset_to_idle(platform_name)
                locked = await self.sync_repo.acquire_sync_lock(platform_name)

        if not locked:
            response.success = False
            response.errors.append(
                f"Platform '{platform_name}' is currently syncing or in error. Reset the state before retrying."
            )
            return response

        try:
            state = await self.sync_repo.get_by_platform(platform_name)
            last_sync = state.last_successful_sync if state else None
            fetch_since = (
                datetime(2026, 1, 1, tzinfo=timezone.utc)
                if last_sync is None
                else last_sync - timedelta(minutes=SYNC_BUFFER_MINUTES)
            )
            normalized_records = await self._fetch_platform_records(platform_name, client, fetch_since, None, source)
            await self._ingest_records(normalized_records, response)
            await self.sync_repo.release_sync_success(platform_name)
            await self.session.commit()
        except Exception as exc:
            await self.session.rollback()
            error_msg = f"{type(exc).__name__}: {exc}"
            logger.exception("Return sync failed for %s", platform_name)
            await self.sync_repo.release_sync_error(platform_name, error_msg)
            await self.session.commit()
            response.success = False
            response.errors.append(error_msg)
        return response

    async def sync_platform_range(
        self,
        platform_name: str,
        client: BasePlatformClient,
        since: datetime,
        until: datetime,
        *,
        source: str,
    ) -> ReturnSyncResponse:
        response = ReturnSyncResponse(platform=platform_name)
        try:
            normalized_records = await self._fetch_platform_records(platform_name, client, since, until, source)
            await self._ingest_records(normalized_records, response)
            await self.session.commit()
        except Exception as exc:
            await self.session.rollback()
            logger.exception("Return range sync failed for %s", platform_name)
            response.success = False
            response.errors.append(f"{type(exc).__name__}: {exc}")
        return response

    async def import_amazon_returns_csv(self, file_content: str) -> ReturnSyncResponse:
        response = ReturnSyncResponse(platform="AMAZON")
        records = self._normalize_amazon_csv_records(file_content)

        try:
            await self._ingest_records(records, response)
            await self.session.commit()
        except Exception as exc:
            await self.session.rollback()
            response.success = False
            response.errors.append(f"{type(exc).__name__}: {exc}")
        return response

    def _normalize_amazon_csv_records(self, file_content: str) -> list[NormalizedReturnRecord]:
        rows = self._read_amazon_csv_rows(file_content)
        if not rows:
            return []
        headers = set(rows[0].keys())
        if {"return-date", "order-id", "detailed-disposition"}.issubset(headers):
            return self._normalize_amazon_fba_return_rows(rows)
        if {"order-id", "return-quantity", "amazon-rma-id"}.issubset(headers):
            return self._normalize_amazon_return_report_rows(rows)
        return self._normalize_amazon_cancel_order_rows(rows)

    def _read_amazon_csv_rows(self, file_content: str) -> list[dict[str, str]]:
        lines = file_content.splitlines()
        if not lines:
            return []
        delimiter = "\t" if lines[0].count("\t") > lines[0].count(",") else ","
        reader = csv.DictReader(lines, delimiter=delimiter)
        rows: list[dict[str, str]] = []
        for row in reader:
            normalized = {
                _normalize_header(key): str(value or "").strip()
                for key, value in row.items()
                if key is not None
            }
            if any(normalized.values()):
                rows.append(normalized)
        return rows

    def _normalize_amazon_cancel_order_rows(
        self,
        rows: Sequence[dict[str, str]],
    ) -> list[NormalizedReturnRecord]:
        records: dict[str, NormalizedReturnRecord] = {}
        for row in rows:
            if row.get("order-status", "").strip().lower() != "cancelled":
                continue

            amazon_order_id = row.get("amazon-order-id", "").strip()
            if not amazon_order_id:
                continue

            if amazon_order_id not in records:
                fc = row.get("fulfillment-channel", "").strip().lower()
                fulfillment_channel = OrderFulfillmentChannel.SELF_FULFILLED
                if fc == "amazon":
                    fulfillment_channel = OrderFulfillmentChannel.AMAZON_FBA

                records[amazon_order_id] = NormalizedReturnRecord(
                    external_record_key=amazon_order_id,
                    external_order_id=amazon_order_id,
                    platform=OrderPlatform.AMAZON,
                    source="AMAZON_CSV",
                    normalized_status=ReturnNormalizedStatus.CANCELLED,
                    fulfillment_channel=fulfillment_channel,
                    ordered_at=_parse_datetime(row.get("purchase-date")),
                    event_at=_parse_datetime(row.get("last-updated-date")),
                    currency=row.get("currency") or "USD",
                    items=[],
                    order_total_amount=Decimal("0"),
                    refunded_amount=Decimal("0"),
                    raw_payload={"rows": []},
                )

            item = NormalizedReturnItem(
                external_item_id=row.get("order-item-id"),
                external_sku=row.get("sku"),
                item_name=row.get("product-name") or "Unknown",
                ordered_qty=_safe_int(row.get("quantity")),
                cancelled_qty=_safe_int(row.get("quantity")),
                refunded_amount=_to_decimal(row.get("item-price")) + _to_decimal(row.get("item-tax")),
                payload=row,
            )
            records[amazon_order_id].items.append(item)
            records[amazon_order_id].order_total_amount += item.refunded_amount
            records[amazon_order_id].refunded_amount += item.refunded_amount
            records[amazon_order_id].raw_payload["rows"].append(row)
        return list(records.values())

    def _normalize_amazon_return_report_rows(
        self,
        rows: Sequence[dict[str, str]],
    ) -> list[NormalizedReturnRecord]:
        records: dict[str, NormalizedReturnRecord] = {}
        for row in rows:
            amazon_order_id = row.get("order-id", "").strip()
            if not amazon_order_id:
                continue

            rma_id = row.get("amazon-rma-id") or row.get("merchant-rma-id") or ""
            order_item_id = row.get("order-item-id") or ""
            record_key = f"{amazon_order_id}:{rma_id or order_item_id or row.get('return-request-date')}"
            return_qty = _safe_int(row.get("return-quantity"))
            ordered_qty = _safe_int(row.get("order-quantity")) or return_qty
            refunded_amount = _to_decimal(row.get("refunded-amount"))
            order_amount = _to_decimal(row.get("order-amount"))

            if record_key not in records:
                records[record_key] = NormalizedReturnRecord(
                    external_record_key=record_key,
                    external_order_id=amazon_order_id,
                    external_return_id=rma_id or None,
                    platform=OrderPlatform.AMAZON,
                    source="AMAZON_RETURN_REPORT",
                    normalized_status=ReturnNormalizedStatus.RETURNED,
                    fulfillment_channel=OrderFulfillmentChannel.SELF_FULFILLED,
                    ordered_at=_parse_datetime(row.get("order-date")),
                    event_at=_parse_datetime(row.get("return-delivery-date"))
                    or _parse_datetime(row.get("return-request-date")),
                    last_source_updated_at=_parse_datetime(row.get("return-request-date")),
                    source_status=row.get("return-request-status") or None,
                    source_substatus=row.get("resolution") or None,
                    reason=row.get("return-reason") or None,
                    currency=row.get("currency-code") or "USD",
                    items=[],
                    order_total_amount=Decimal("0"),
                    refunded_amount=Decimal("0"),
                    raw_payload={"rows": []},
                )

            item = NormalizedReturnItem(
                external_item_id=order_item_id or None,
                external_sku=row.get("merchant-sku") or None,
                item_name=row.get("item-name") or "Unknown",
                ordered_qty=ordered_qty,
                returned_qty=return_qty,
                refunded_amount=refunded_amount,
                payload=row,
            )
            record = records[record_key]
            record.items.append(item)
            record.order_total_amount += order_amount
            record.refunded_amount += refunded_amount
            record.raw_payload["rows"].append(row)

        for record in records.values():
            record.normalized_status = self._status_from_return_quantities(record.items)
        return list(records.values())

    def _normalize_amazon_fba_return_rows(
        self,
        rows: Sequence[dict[str, str]],
    ) -> list[NormalizedReturnRecord]:
        records: dict[str, NormalizedReturnRecord] = {}
        for row in rows:
            amazon_order_id = row.get("order-id", "").strip()
            if not amazon_order_id:
                continue

            lpn = row.get("license-plate-number") or ""
            record_key = f"{amazon_order_id}:{lpn or row.get('sku') or row.get('return-date')}"
            return_qty = _safe_int(row.get("quantity"))
            if record_key not in records:
                records[record_key] = NormalizedReturnRecord(
                    external_record_key=record_key,
                    external_order_id=amazon_order_id,
                    external_return_id=lpn or None,
                    platform=OrderPlatform.AMAZON,
                    source="AMAZON_FBA_RETURN_REPORT",
                    normalized_status=ReturnNormalizedStatus.RETURNED,
                    fulfillment_channel=OrderFulfillmentChannel.AMAZON_FBA,
                    event_at=_parse_datetime(row.get("return-date")),
                    last_source_updated_at=_parse_datetime(row.get("return-date")),
                    source_status=row.get("status") or None,
                    source_substatus=row.get("detailed-disposition") or None,
                    reason=row.get("reason") or None,
                    items=[],
                    raw_payload={"rows": []},
                )

            item = NormalizedReturnItem(
                external_item_id=row.get("fnsku") or row.get("asin") or None,
                external_sku=row.get("sku") or None,
                item_name=row.get("product-name") or "Unknown",
                ordered_qty=return_qty,
                returned_qty=return_qty,
                payload=row,
            )
            record = records[record_key]
            record.items.append(item)
            record.raw_payload["rows"].append(row)

        for record in records.values():
            record.normalized_status = self._status_from_return_quantities(record.items)
        return list(records.values())

    def _status_from_return_quantities(
        self,
        items: Sequence[NormalizedReturnItem],
    ) -> ReturnNormalizedStatus:
        ordered_qty = sum(_safe_int(item.ordered_qty) for item in items)
        returned_qty = sum(_safe_int(item.returned_qty) for item in items)
        if ordered_qty and 0 < returned_qty < ordered_qty:
            return ReturnNormalizedStatus.PARTIALLY_RETURNED
        return ReturnNormalizedStatus.RETURNED

    async def rematch_record(self, record_id: int) -> ReturnRecord:
        record = await self.record_repo.get_with_items(record_id)
        if not record:
            raise LookupError(f"Return record {record_id} not found")
            
        linked_order = await self._find_linked_order(record.platform, record.external_order_id)
        if not linked_order:
            record.zoho_sync_status = ReturnZohoSyncStatus.MISSING_LOCAL_ORDER
            await self.session.commit()
            return record
            
        record.linked_order_id = linked_order.id
        record.zoho_sync_status = ReturnZohoSyncStatus.PENDING

        if not record.customer_name and linked_order.customer_name:
            record.customer_name = linked_order.customer_name
        if not record.customer_email and linked_order.customer_email:
            record.customer_email = linked_order.customer_email
        if not record.currency and linked_order.currency:
            record.currency = linked_order.currency
        
        status_map = {
            ReturnNormalizedStatus.RETURNED: OrderStatus.RETURN,
            ReturnNormalizedStatus.PARTIALLY_RETURNED: OrderStatus.RETURN,
            ReturnNormalizedStatus.REFUNDED: OrderStatus.REFUNDED,
            ReturnNormalizedStatus.PARTIALLY_REFUNDED: OrderStatus.PARTIALLY_REFUNDED,
            ReturnNormalizedStatus.CANCELLED: OrderStatus.CANCELLED,
            ReturnNormalizedStatus.PARTIALLY_CANCELLED: OrderStatus.CANCELLED,
        }
        new_status = status_map.get(record.normalized_status)
        if new_status:
            linked_order.status = new_status
            
        # Also re-link items
        _, linked_items_count = self._build_item_rows(
            linked_order, 
            [NormalizedReturnItem(
                external_item_id=item.external_item_id,
                external_sku=item.external_sku,
                item_name=item.item_name,
                ordered_qty=item.ordered_qty,
                returned_qty=item.returned_qty,
                cancelled_qty=item.cancelled_qty,
                refunded_amount=item.refunded_amount,
                payload=item.item_payload
            ) for item in record.items]
        )
        
        # Link order items properly
        for item in record.items:
            linked_item = self._link_order_item(
                linked_order,
                NormalizedReturnItem(
                    external_item_id=item.external_item_id,
                    external_sku=item.external_sku,
                    item_name=item.item_name,
                )
            )
            if linked_item:
                item.linked_order_item_id = linked_item.id

        await self.session.commit()
        return record

    async def _ensure_sync_state(self, platform_name: str) -> None:
        if await self.sync_repo.get_by_platform(platform_name):
            return
        self.session.add(
            ReturnSyncState(
                platform_name=platform_name,
                current_status=IntegrationSyncStatus.IDLE,
            )
        )
        await self.session.flush()

    async def _ingest_records(
        self,
        records: Sequence[NormalizedReturnRecord],
        response: ReturnSyncResponse,
    ) -> None:
        for record in records:
            result = await self._upsert_record(record, response)
            if result == "unchanged":
                response.skipped_duplicates += 1

    async def _upsert_record(
        self,
        record: NormalizedReturnRecord,
        response: ReturnSyncResponse,
    ) -> str:
        linked_order = await self._find_linked_order(record.platform, record.external_order_id)
        linked_order_id = linked_order.id if linked_order else None
        
        if linked_order:
            if not record.customer_name and linked_order.customer_name:
                record.customer_name = linked_order.customer_name
            if not record.customer_email and linked_order.customer_email:
                record.customer_email = linked_order.customer_email
            if not record.currency and linked_order.currency:
                record.currency = linked_order.currency

        zoho_sync_status = ReturnZohoSyncStatus.PENDING

        if linked_order_id is not None:
            response.linked_orders += 1
            
            status_map = {
                ReturnNormalizedStatus.RETURNED: OrderStatus.RETURN,
                ReturnNormalizedStatus.PARTIALLY_RETURNED: OrderStatus.RETURN,
                ReturnNormalizedStatus.REFUNDED: OrderStatus.REFUNDED,
                ReturnNormalizedStatus.PARTIALLY_REFUNDED: OrderStatus.PARTIALLY_REFUNDED,
                ReturnNormalizedStatus.CANCELLED: OrderStatus.CANCELLED,
                ReturnNormalizedStatus.PARTIALLY_CANCELLED: OrderStatus.CANCELLED,
            }
            new_status = status_map.get(record.normalized_status)
            if new_status:
                linked_order.status = new_status
        else:
            zoho_sync_status = ReturnZohoSyncStatus.MISSING_LOCAL_ORDER

        item_rows, linked_items = self._build_item_rows(linked_order, record.items)
        response.linked_items += linked_items

        payload = {
            "platform": record.platform,
            "source": record.source,
            "external_record_key": record.external_record_key,
            "external_order_id": record.external_order_id,
            "external_return_id": record.external_return_id,
            "linked_order_id": linked_order_id,
            "customer_name": record.customer_name,
            "customer_email": record.customer_email,
            "ordered_at": record.ordered_at,
            "event_at": record.event_at,
            "last_source_updated_at": record.last_source_updated_at,
            "normalized_status": record.normalized_status,
            "source_status": record.source_status,
            "source_substatus": record.source_substatus,
            "reason": record.reason,
            "fulfillment_channel": record.fulfillment_channel,
            "order_total_amount": record.order_total_amount,
            "refunded_amount": record.refunded_amount,
            "currency": record.currency,
            "raw_payload": record.raw_payload,
            "zoho_sync_status": zoho_sync_status,
        }
        incoming_snapshot = self._build_snapshot(payload, item_rows)

        existing = await self.record_repo.get_by_external_key(record.platform, record.external_record_key)
        if existing is None:
            created = await self.record_repo.create(payload)
            for item_row in item_rows:
                self.session.add(ReturnItem(return_record_id=created.id, **item_row))
                response.new_items += 1
            response.new_records += 1
            await self.session.flush()
            return "created"

        current_snapshot = self._build_current_snapshot(existing)
        if current_snapshot == incoming_snapshot:
            return "unchanged"

        for field, value in payload.items():
            setattr(existing, field, value)
        for item in list(existing.items):
            await self.session.delete(item)
        await self.session.flush()
        for item_row in item_rows:
            self.session.add(ReturnItem(return_record_id=existing.id, **item_row))
            response.new_items += 1
        self.session.add(existing)
        await self.session.flush()
        response.updated_records += 1
        return "updated"

    async def _find_linked_order(self, platform: OrderPlatform, external_order_id: str) -> Optional[Order]:
        if hasattr(type(self.order_repo), "get_by_external_reference"):
            order = await self.order_repo.get_by_external_reference(platform, external_order_id)
        else:
            order = await self.order_repo.get_by_external_id(platform, external_order_id)
        if order is None:
            return None
        return await self.order_repo.get_with_items(order.id)

    def _build_item_rows(
        self,
        order: Optional[Order],
        items: Sequence[NormalizedReturnItem],
    ) -> tuple[list[dict[str, Any]], int]:
        rows: list[dict[str, Any]] = []
        linked_count = 0
        for item in items:
            linked_order_item = self._link_order_item(order, item)
            if linked_order_item is not None:
                linked_count += 1
                if not item.item_name or item.item_name == "Unknown" or item.item_name == "Unknown Item":
                    item.item_name = linked_order_item.item_name
                if not item.external_sku and linked_order_item.external_sku:
                    item.external_sku = linked_order_item.external_sku
            rows.append(
                {
                    "linked_order_item_id": linked_order_item.id if linked_order_item else None,
                    "external_item_id": item.external_item_id,
                    "external_sku": item.external_sku,
                    "item_name": item.item_name,
                    "ordered_qty": max(int(item.ordered_qty or 0), 0),
                    "returned_qty": max(int(item.returned_qty or 0), 0),
                    "cancelled_qty": max(int(item.cancelled_qty or 0), 0),
                    "refunded_amount": item.refunded_amount,
                    "item_payload": item.payload,
                }
            )
        return rows, linked_count

    def _link_order_item(self, order: Optional[Order], item: NormalizedReturnItem) -> Optional[OrderItem]:
        if order is None:
            return None
        ext_id = _normalize_text(item.external_item_id)
        ext_sku = _normalize_text(item.external_sku)
        title = _normalize_text(item.item_name)
        for existing in order.items or []:
            if ext_id and _normalize_text(existing.external_item_id) == ext_id:
                return existing
        for existing in order.items or []:
            if ext_sku and _normalize_text(existing.external_sku) == ext_sku:
                return existing
        for existing in order.items or []:
            if title and _normalize_text(existing.item_name) == title:
                return existing
        return None

    @staticmethod
    def _build_snapshot(payload: dict[str, Any], item_rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
        return {
            **payload,
            "normalized_status": payload["normalized_status"].value
            if hasattr(payload["normalized_status"], "value")
            else str(payload["normalized_status"]),
            "fulfillment_channel": payload.get("fulfillment_channel").value
            if hasattr(payload.get("fulfillment_channel"), "value")
            else str(payload.get("fulfillment_channel")),
            "zoho_sync_status": payload.get("zoho_sync_status").value
            if hasattr(payload.get("zoho_sync_status"), "value")
            else str(payload.get("zoho_sync_status")),
            "order_total_amount": str(_to_decimal(payload["order_total_amount"])),
            "refunded_amount": str(_to_decimal(payload["refunded_amount"])),
            "items": [
                {
                    **item,
                    "refunded_amount": str(_to_decimal(item["refunded_amount"])),
                }
                for item in item_rows
            ],
        }

    def _build_current_snapshot(self, existing: ReturnRecord) -> dict[str, Any]:
        item_rows = [
            {
                "linked_order_item_id": item.linked_order_item_id,
                "external_item_id": item.external_item_id,
                "external_sku": item.external_sku,
                "item_name": item.item_name,
                "ordered_qty": item.ordered_qty,
                "returned_qty": item.returned_qty,
                "cancelled_qty": item.cancelled_qty,
                "refunded_amount": item.refunded_amount,
                "item_payload": item.item_payload,
            }
            for item in existing.items
        ]
        payload = {
            "platform": existing.platform,
            "source": existing.source,
            "external_record_key": existing.external_record_key,
            "external_order_id": existing.external_order_id,
            "external_return_id": existing.external_return_id,
            "linked_order_id": existing.linked_order_id,
            "customer_name": existing.customer_name,
            "customer_email": existing.customer_email,
            "ordered_at": existing.ordered_at,
            "event_at": existing.event_at,
            "last_source_updated_at": existing.last_source_updated_at,
            "normalized_status": existing.normalized_status,
            "source_status": existing.source_status,
            "source_substatus": existing.source_substatus,
            "reason": existing.reason,
            "fulfillment_channel": existing.fulfillment_channel,
            "order_total_amount": existing.order_total_amount,
            "refunded_amount": existing.refunded_amount,
            "currency": existing.currency,
            "raw_payload": existing.raw_payload,
            "zoho_sync_status": existing.zoho_sync_status,
        }
        return self._build_snapshot(payload, item_rows)

    async def _fetch_platform_records(
        self,
        platform_name: str,
        client: BasePlatformClient,
        since: datetime,
        until: Optional[datetime],
        source: str,
    ) -> list[NormalizedReturnRecord]:
        platform = _PLATFORM_MAP[platform_name]
        if platform in {OrderPlatform.EBAY_MEKONG, OrderPlatform.EBAY_USAV, OrderPlatform.EBAY_DRAGON}:
            return await self._fetch_ebay_records(platform, client, since, until, source)
        if platform == OrderPlatform.ECWID:
            return await self._fetch_ecwid_records(platform, client, since, until, source)
        if platform == OrderPlatform.WALMART:
            return await self._fetch_walmart_records(platform, client, since, until, source)
        return []

    async def _fetch_ebay_records(
        self,
        platform: OrderPlatform,
        client: BasePlatformClient,
        since: datetime,
        until: Optional[datetime],
        source: str,
    ) -> list[NormalizedReturnRecord]:
        raw_orders: list[dict[str, Any]] = []
        if hasattr(client, "fetch_orders_raw"):
            raw_orders = await client.fetch_orders_raw(
                since=since,
                until=until,
                date_field="lastmodifieddate",
            )
        else:
            orders = await client.fetch_orders(since=since, until=until)
            raw_orders = [ext_order.raw_data or {} for ext_order in orders if isinstance(ext_order.raw_data, dict)]
        return_requests = []
        if hasattr(client, "fetch_return_requests"):
            return_requests = await client.fetch_return_requests(since=since, until=until)

        records: list[NormalizedReturnRecord] = []
        return_order_ids = {
            str(req.get("legacyOrderId") or req.get("orderId") or req.get("itemizedOrderId") or "").strip()
            for req in return_requests
            if isinstance(req, dict)
        }
        for raw_order in raw_orders:
            if not self._is_ebay_order_candidate(raw_order):
                continue
            normalized = self._normalize_ebay_order_record(platform, source, raw_order)
            if normalized is None:
                continue
            if self._ebay_order_needs_detail(raw_order) and hasattr(client, "get_order"):
                order_id = str(raw_order.get("orderId") or "").strip()
                if order_id:
                    detailed_order = await client.get_order(order_id)
                    if detailed_order is not None and isinstance(detailed_order.raw_data, dict):
                        detailed_normalized = self._normalize_ebay_order_record(
                            platform,
                            source,
                            detailed_order.raw_data,
                        )
                        if detailed_normalized is not None:
                            normalized = detailed_normalized
            if normalized.normalized_status in {
                ReturnNormalizedStatus.REFUNDED,
                ReturnNormalizedStatus.PARTIALLY_REFUNDED,
            } and normalized.external_order_id in return_order_ids:
                continue
            records.append(normalized)

        for raw_case in return_requests:
            normalized_case = self._normalize_ebay_return_case(platform, source, raw_case)
            if normalized_case is not None:
                records.append(normalized_case)
        return records

    async def _fetch_ecwid_records(
        self,
        platform: OrderPlatform,
        client: BasePlatformClient,
        since: datetime,
        until: Optional[datetime],
        source: str,
    ) -> list[NormalizedReturnRecord]:
        candidates: dict[str, NormalizedReturnRecord] = {}
        fetch_specs = [
            {"status": "CANCELLED"},
            {"status": "REFUNDED"},
            {"status": "PARTIALLY_REFUNDED"},
            {"fulfillment_status": "RETURNED"},
        ]
        for spec in fetch_specs:
            orders = await client.fetch_orders(since=since, until=until, **spec)
            for ext_order in orders:
                record = self._normalize_ecwid_order_record(platform, source, ext_order.raw_data or {})
                if record is None:
                    continue
                existing = candidates.get(record.external_record_key)
                candidates[record.external_record_key] = self._merge_record(existing, record)
        return list(candidates.values())

    async def _fetch_walmart_records(
        self,
        platform: OrderPlatform,
        client: BasePlatformClient,
        since: datetime,
        until: Optional[datetime],
        source: str,
    ) -> list[NormalizedReturnRecord]:
        orders = await client.fetch_orders(since=since, until=until)
        records: list[NormalizedReturnRecord] = []
        for ext_order in orders:
            normalized = self._normalize_walmart_order_record(platform, source, ext_order.raw_data or {})
            if normalized is not None:
                records.append(normalized)

        if hasattr(client, "fetch_returns"):
            return_orders = await client.fetch_returns(since=since, until=until)
            for raw_return in return_orders:
                normalized = self._normalize_walmart_return_record(platform, source, raw_return)
                if normalized is not None:
                    records.append(normalized)
        return records

    def _merge_record(
        self,
        existing: Optional[NormalizedReturnRecord],
        incoming: NormalizedReturnRecord,
    ) -> NormalizedReturnRecord:
        if existing is None:
            return incoming
        if _status_rank(incoming.normalized_status) > _status_rank(existing.normalized_status):
            winner = incoming
            loser = existing
        else:
            winner = existing
            loser = incoming
        winner.refunded_amount = max(winner.refunded_amount, loser.refunded_amount)
        if not winner.reason and loser.reason:
            winner.reason = loser.reason
        return winner

    def _normalize_ebay_order_record(
        self,
        platform: OrderPlatform,
        source: str,
        raw: dict[str, Any],
    ) -> Optional[NormalizedReturnRecord]:
        cancel_status = raw.get("cancelStatus") or {}
        cancel_state = str(cancel_status.get("cancelState") or "").upper()
        cancel_requests = _coerce_list(cancel_status.get("cancelRequests"))
        cancel_reason = None
        if cancel_requests and isinstance(cancel_requests[0], dict):
            cancel_reason = str(cancel_requests[0].get("cancelReason") or "").strip() or None
        payment_status = str(
            raw.get("orderPaymentStatus")
            or raw.get("paymentSummary", {}).get("paymentStatus")
            or raw.get("paymentStatus")
            or ""
        ).upper()
        line_items = _coerce_list(raw.get("lineItems"))
        refunded_amount = self._extract_ebay_refunded_amount(raw)
        order_id = str(raw.get("orderId") or raw.get("legacyOrderId") or "").strip()
        if not order_id:
            return None
        customer_name = (
            raw.get("buyer", {}).get("username")
            or raw.get("buyer", {}).get("buyerRegistrationAddress", {}).get("fullName")
            or raw.get("fulfillmentStartInstructions", [{}])[0].get("shippingStep", {}).get("shipTo", {}).get("fullName")
        )
        customer_email = raw.get("buyer", {}).get("email")
        ordered_at = _parse_datetime(raw.get("creationDate"))

        items: list[NormalizedReturnItem] = []
        total_qty = 0
        cancelled_qty = 0
        for item in line_items:
            qty = int(item.get("quantity") or 0)
            total_qty += qty
            item_cancelled_qty = int(item.get("cancelledQuantity") or item.get("cancelQuantity") or 0)
            if cancel_state == "CANCELED" and item_cancelled_qty == 0:
                item_cancelled_qty = qty
            cancelled_qty += item_cancelled_qty
            items.append(
                NormalizedReturnItem(
                    external_item_id=str(item.get("legacyItemId") or item.get("itemId") or item.get("lineItemId") or "") or None,
                    external_sku=item.get("sku"),
                    item_name=item.get("title") or "Unknown Item",
                    ordered_qty=qty,
                    cancelled_qty=item_cancelled_qty,
                    refunded_amount=Decimal("0"),
                    payload=item,
                )
            )

        if cancel_state == "CANCELED":
            status = (
                ReturnNormalizedStatus.PARTIALLY_CANCELLED
                if total_qty and 0 < cancelled_qty < total_qty
                else ReturnNormalizedStatus.CANCELLED
            )
            return NormalizedReturnRecord(
                external_record_key=f"order:{order_id}",
                external_order_id=order_id,
                platform=platform,
                source=source,
                external_return_id=None,
                customer_name=customer_name,
                customer_email=customer_email,
                ordered_at=ordered_at,
                event_at=_parse_datetime(cancel_status.get("cancelledDate") or raw.get("cancelledDate")) or ordered_at,
                last_source_updated_at=_parse_datetime(cancel_status.get("cancelledDate") or raw.get("lastModifiedDate") or raw.get("modificationDate")),
                normalized_status=status,
                source_status=cancel_state,
                source_substatus=cancel_reason,
                reason=cancel_reason,
                order_total_amount=_to_decimal(raw.get("pricingSummary", {}).get("total", {}).get("value") or 0),
                refunded_amount=refunded_amount,
                currency=raw.get("pricingSummary", {}).get("total", {}).get("currency") or "USD",
                raw_payload=raw,
                items=items,
            )

        if payment_status in {"FULLY_REFUNDED", "REFUNDED", "PARTIALLY_REFUNDED"} or refunded_amount > Decimal("0"):
            status = (
                ReturnNormalizedStatus.PARTIALLY_REFUNDED
                if payment_status == "PARTIALLY_REFUNDED"
                else ReturnNormalizedStatus.REFUNDED
            )
            return NormalizedReturnRecord(
                external_record_key=f"refund:{order_id}",
                external_order_id=order_id,
                platform=platform,
                source=source,
                customer_name=customer_name,
                customer_email=customer_email,
                ordered_at=ordered_at,
                event_at=_parse_datetime(raw.get("lastModifiedDate") or raw.get("modificationDate")) or ordered_at,
                last_source_updated_at=_parse_datetime(raw.get("lastModifiedDate") or raw.get("modificationDate")),
                normalized_status=status,
                source_status=payment_status or None,
                order_total_amount=_to_decimal(raw.get("pricingSummary", {}).get("total", {}).get("value") or 0),
                refunded_amount=refunded_amount,
                currency=raw.get("pricingSummary", {}).get("total", {}).get("currency") or "USD",
                raw_payload=raw,
                items=items,
            )
        return None

    @staticmethod
    def _is_ebay_order_candidate(raw: dict[str, Any]) -> bool:
        cancel_state = str(raw.get("cancelStatus", {}).get("cancelState") or "").upper()
        refunds = _coerce_list(raw.get("paymentSummary", {}).get("refunds"))
        payment_status = str(
            raw.get("orderPaymentStatus")
            or raw.get("paymentSummary", {}).get("paymentStatus")
            or raw.get("paymentStatus")
            or ""
        ).upper()
        return (
            (cancel_state and cancel_state != "NONE_REQUESTED")
            or bool(refunds)
            or payment_status in {"FULLY_REFUNDED", "PARTIALLY_REFUNDED", "REFUNDED"}
        )

    @staticmethod
    def _ebay_order_needs_detail(raw: dict[str, Any]) -> bool:
        cancel_state = str(raw.get("cancelStatus", {}).get("cancelState") or "").upper()
        refunds = _coerce_list(raw.get("paymentSummary", {}).get("refunds"))
        payment_status = str(
            raw.get("orderPaymentStatus")
            or raw.get("paymentSummary", {}).get("paymentStatus")
            or raw.get("paymentStatus")
            or ""
        ).upper()
        order_total = _to_decimal(raw.get("pricingSummary", {}).get("total", {}).get("value") or 0)
        refund_total = Decimal("0")
        for refund in refunds:
            if isinstance(refund, dict):
                refund_total += _to_decimal(
                    refund.get("amount", {}).get("value")
                    or refund.get("refundAmount", {}).get("value")
                    or refund.get("amount")
                )
        return (
            not _coerce_list(raw.get("lineItems"))
            or (cancel_state == "NONE_REQUESTED" and bool(refunds))
            or (payment_status in {"FULLY_REFUNDED", "REFUNDED"} and not refunds)
            or (refund_total > Decimal("0") and order_total > Decimal("0") and refund_total > order_total)
        )

    def _normalize_ebay_return_case(
        self,
        platform: OrderPlatform,
        source: str,
        raw_case: dict[str, Any],
    ) -> Optional[NormalizedReturnRecord]:
        return_id = str(raw_case.get("returnId") or raw_case.get("id") or "").strip()
        external_order_id = str(
            raw_case.get("legacyOrderId")
            or raw_case.get("orderId")
            or raw_case.get("itemizedOrderId")
            or ""
        ).strip()
        if not return_id or not external_order_id:
            return None

        raw_items = _coerce_list(
            raw_case.get("items")
            or raw_case.get("returnItems")
            or raw_case.get("returnItem")
        )
        items: list[NormalizedReturnItem] = []
        total_qty = 0
        returned_qty = 0
        refunded_amount = Decimal("0")
        for item in raw_items:
            ordered_qty = int(item.get("quantity") or item.get("orderQuantity") or 0)
            item_returned_qty = int(
                item.get("returnedQuantity")
                or item.get("returnQuantity")
                or item.get("quantity")
                or 0
            )
            total_qty += ordered_qty or item_returned_qty
            returned_qty += item_returned_qty
            item_refunded_amount = _to_decimal(
                item.get("refundAmount", {}).get("value")
                or item.get("amount", {}).get("value")
                or item.get("refundAmount")
            )
            refunded_amount += item_refunded_amount
            items.append(
                NormalizedReturnItem(
                    external_item_id=str(item.get("legacyItemId") or item.get("itemId") or "") or None,
                    external_sku=item.get("sku"),
                    item_name=item.get("title") or item.get("itemName") or "Unknown Item",
                    ordered_qty=ordered_qty or item_returned_qty,
                    returned_qty=item_returned_qty,
                    refunded_amount=item_refunded_amount,
                    payload=item,
                )
            )

        status = (
            ReturnNormalizedStatus.PARTIALLY_RETURNED
            if total_qty and 0 < returned_qty < total_qty
            else ReturnNormalizedStatus.RETURNED
        )
        if returned_qty == 0 and refunded_amount > Decimal("0"):
            status = ReturnNormalizedStatus.REFUNDED

        return NormalizedReturnRecord(
            external_record_key=f"return:{return_id}",
            external_order_id=external_order_id,
            external_return_id=return_id,
            platform=platform,
            source=source,
            customer_name=raw_case.get("buyerLoginName") or raw_case.get("buyerName"),
            customer_email=raw_case.get("buyerEmail"),
            ordered_at=_parse_datetime(raw_case.get("creationDate") or raw_case.get("orderCreationDate")),
            event_at=_parse_datetime(raw_case.get("lastModifiedDate") or raw_case.get("creationDate")),
            last_source_updated_at=_parse_datetime(raw_case.get("lastModifiedDate")),
            normalized_status=status,
            source_status=str(raw_case.get("status") or raw_case.get("returnState") or "") or None,
            source_substatus=str(raw_case.get("state") or raw_case.get("subStatus") or "") or None,
            reason=str(raw_case.get("returnReason") or raw_case.get("reason") or "") or None,
            order_total_amount=_to_decimal(raw_case.get("orderAmount", {}).get("value") or 0),
            refunded_amount=refunded_amount,
            currency=str(raw_case.get("currency") or "USD"),
            raw_payload=raw_case,
            items=items,
        )

    def _normalize_ecwid_order_record(
        self,
        platform: OrderPlatform,
        source: str,
        raw: dict[str, Any],
    ) -> Optional[NormalizedReturnRecord]:
        order_id = str(raw.get("id") or raw.get("orderNumber") or "").strip()
        if not order_id:
            return None
        payment_status = str(raw.get("paymentStatus") or "").upper()
        fulfillment_status = str(raw.get("fulfillmentStatus") or "").upper()
        refunded_amount = _to_decimal(raw.get("refundedAmount") or 0)
        is_refund_only = (
            payment_status in {"REFUNDED", "PARTIALLY_REFUNDED"}
            and fulfillment_status != "RETURNED"
            and refunded_amount > Decimal("0")
        )
        raw_items = _coerce_list(raw.get("items"))
        allocate_refund_to_single_line = refunded_amount > Decimal("0") and len(raw_items) == 1
        items: list[NormalizedReturnItem] = []
        total_qty = 0
        for item in raw_items:
            qty = int(item.get("quantity") or 0)
            total_qty += qty
            items.append(
                NormalizedReturnItem(
                    external_item_id=str(item.get("productId") or item.get("id") or "") or None,
                    external_sku=item.get("sku"),
                    item_name=item.get("name") or "Unknown Item",
                    ordered_qty=qty,
                    returned_qty=qty if fulfillment_status == "RETURNED" or allocate_refund_to_single_line else 0,
                    cancelled_qty=qty if payment_status == "CANCELLED" else 0,
                    refunded_amount=refunded_amount if allocate_refund_to_single_line else Decimal("0"),
                    payload=item,
                )
            )
        if fulfillment_status == "RETURNED":
            status = ReturnNormalizedStatus.RETURNED
        elif payment_status == "CANCELLED":
            status = ReturnNormalizedStatus.CANCELLED
        elif payment_status == "PARTIALLY_REFUNDED":
            status = ReturnNormalizedStatus.PARTIALLY_REFUNDED
        elif payment_status == "REFUNDED":
            status = ReturnNormalizedStatus.REFUNDED
        else:
            return None

        return NormalizedReturnRecord(
            external_record_key=f"order:{order_id}",
            external_order_id=order_id,
            platform=platform,
            source=source,
            customer_name=raw.get("shippingPerson", {}).get("name"),
            customer_email=raw.get("email"),
            ordered_at=_parse_datetime(raw.get("createDate") or raw.get("createTimestamp")),
            event_at=_parse_datetime(raw.get("updateDate") or raw.get("paymentStatusUpdated") or raw.get("fulfillmentStatusUpdated"))
            or _parse_datetime(raw.get("createDate") or raw.get("createTimestamp")),
            last_source_updated_at=_parse_datetime(raw.get("updateDate")),
            normalized_status=status,
            source_status=payment_status or None,
            source_substatus=fulfillment_status or None,
            reason=str(raw.get("paymentMethod") or raw.get("orderComments") or "") or None,
            order_total_amount=_to_decimal(raw.get("total") or 0),
            refunded_amount=refunded_amount,
            currency=str(raw.get("currency") or "USD"),
            raw_payload=raw,
            items=items,
        )

    def _normalize_walmart_order_record(
        self,
        platform: OrderPlatform,
        source: str,
        raw: dict[str, Any],
    ) -> Optional[NormalizedReturnRecord]:
        order_id = str(raw.get("purchaseOrderId") or raw.get("customerOrderId") or "").strip()
        if not order_id:
            return None

        raw_lines = _coerce_list(raw.get("orderLines", {}).get("orderLine"))
        items: list[NormalizedReturnItem] = []
        total_qty = 0
        cancelled_qty = 0
        for line in raw_lines:
            ordered_qty = int(line.get("orderLineQuantity", {}).get("amount") or 0)
            total_qty += ordered_qty
            cancelled_for_line = 0
            for line_status in _coerce_list(line.get("orderLineStatuses", {}).get("orderLineStatus")):
                status_text = str(line_status.get("status") or "").upper()
                if status_text == "CANCELLED":
                    cancelled_for_line = int(
                        line_status.get("statusQuantity", {}).get("amount")
                        or line_status.get("quantity", {}).get("amount")
                        or ordered_qty
                    )
                    break
            cancelled_qty += cancelled_for_line
            items.append(
                NormalizedReturnItem(
                    external_item_id=str(line.get("lineNumber") or "") or None,
                    external_sku=line.get("item", {}).get("sku"),
                    item_name=line.get("item", {}).get("productName") or "Unknown Item",
                    ordered_qty=ordered_qty,
                    cancelled_qty=cancelled_for_line,
                    payload=line,
                )
            )

        if cancelled_qty <= 0:
            return None
        status = (
            ReturnNormalizedStatus.PARTIALLY_CANCELLED
            if total_qty and cancelled_qty < total_qty
            else ReturnNormalizedStatus.CANCELLED
        )
        return NormalizedReturnRecord(
            external_record_key=f"order:{order_id}:cancel",
            external_order_id=order_id,
            platform=platform,
            source=source,
            customer_name=raw.get("shippingInfo", {}).get("postalAddress", {}).get("name"),
            customer_email=raw.get("customerEmailId"),
            ordered_at=_parse_datetime(raw.get("orderDate")),
            event_at=_parse_datetime(raw.get("lastModifiedDate")) or _parse_datetime(raw.get("orderDate")),
            last_source_updated_at=_parse_datetime(raw.get("lastModifiedDate")),
            normalized_status=status,
            source_status="CANCELLED",
            order_total_amount=_to_decimal(raw.get("orderTotal", {}).get("amount") or 0),
            refunded_amount=Decimal("0"),
            currency=str(raw.get("orderTotal", {}).get("currency") or "USD"),
            raw_payload=raw,
            items=items,
        )

    def _normalize_walmart_return_record(
        self,
        platform: OrderPlatform,
        source: str,
        raw: dict[str, Any],
    ) -> Optional[NormalizedReturnRecord]:
        return_id = str(raw.get("returnOrderId") or raw.get("returnOrder", {}).get("returnOrderId") or "").strip()
        if not return_id:
            return None
        order_id = str(raw.get("customerOrderId") or raw.get("purchaseOrderId") or raw.get("orderId") or "").strip()
        return_order_lines = raw.get("returnOrderLines")
        if isinstance(return_order_lines, dict):
            raw_lines = _coerce_list(return_order_lines.get("returnOrderLine"))
        else:
            raw_lines = _coerce_list(return_order_lines or raw.get("returnOrderLine"))
        items: list[NormalizedReturnItem] = []
        total_qty = 0
        returned_qty = 0
        refunded_amount = Decimal("0")
        for line in raw_lines:
            ordered_qty = int(line.get("quantity", {}).get("amount") or line.get("orderedQuantity") or 0)
            line_returned_qty = int(
                line.get("returnQuantity", {}).get("amount")
                or line.get("returnOrderLineQuantity", {}).get("amount")
                or line.get("quantity", {}).get("amount")
                or 0
            )
            total_qty += ordered_qty or line_returned_qty
            returned_qty += line_returned_qty
            line_refunded_amount = _to_decimal(
                line.get("refund", {}).get("amount")
                or line.get("refundAmount", {}).get("amount")
                or line.get("refundedAmount")
                or 0
            )
            refunded_amount += line_refunded_amount
            items.append(
                NormalizedReturnItem(
                    external_item_id=str(line.get("lineNumber") or line.get("orderLineNumber") or "") or None,
                    external_sku=line.get("item", {}).get("sku") or line.get("sku"),
                    item_name=line.get("item", {}).get("productName") or line.get("productName") or "Unknown Item",
                    ordered_qty=ordered_qty or line_returned_qty,
                    returned_qty=line_returned_qty,
                    refunded_amount=line_refunded_amount,
                    payload=line,
                )
            )

        status = (
            ReturnNormalizedStatus.PARTIALLY_RETURNED
            if total_qty and 0 < returned_qty < total_qty
            else ReturnNormalizedStatus.RETURNED
        )
        if returned_qty == 0 and refunded_amount > Decimal("0"):
            status = ReturnNormalizedStatus.PARTIALLY_REFUNDED if len(items) > 1 else ReturnNormalizedStatus.REFUNDED

        return NormalizedReturnRecord(
            external_record_key=f"return:{return_id}",
            external_order_id=order_id or return_id,
            external_return_id=return_id,
            platform=platform,
            source=source,
            customer_name=raw.get("customerName"),
            customer_email=raw.get("customerEmailId"),
            ordered_at=_parse_datetime(raw.get("orderDate")),
            event_at=_parse_datetime(raw.get("returnDate")) or _parse_datetime(raw.get("lastUpdatedDate")),
            last_source_updated_at=_parse_datetime(raw.get("lastUpdatedDate") or raw.get("returnDate")),
            normalized_status=status,
            source_status=str(raw.get("status") or raw.get("returnOrderStatus") or "") or None,
            source_substatus=str(raw.get("currentRefundStatus") or "") or None,
            reason=str(raw.get("returnReason") or "") or None,
            order_total_amount=_to_decimal(raw.get("orderAmount", {}).get("amount") or 0),
            refunded_amount=refunded_amount,
            currency=str(raw.get("currency") or raw.get("orderAmount", {}).get("currency") or "USD"),
            raw_payload=raw,
            items=items,
        )

    @staticmethod
    def _extract_ebay_refunded_amount(raw: dict[str, Any]) -> Decimal:
        amount = Decimal("0")
        refunds = _coerce_list(raw.get("paymentSummary", {}).get("refunds")) + _coerce_list(raw.get("refunds"))
        for refund in refunds:
            amount += _to_decimal(refund.get("amount", {}).get("value") or refund.get("refundAmount", {}).get("value") or refund.get("amount"))
        if amount > Decimal("0"):
            return amount
        return _to_decimal(
            raw.get("pricingSummary", {}).get("refund")
            or raw.get("refundAmount", {}).get("value")
            or raw.get("refundAmount")
            or 0
        )
