"""
Order module API routes.

Endpoints
---------
Synchronization
    POST /orders/sync            – Trigger "Safe Sync" for one or all platforms.
    POST /orders/sync/refresh-matching – Re-check unmatched items against listing mappings.
    GET  /orders/sync/status     – Dashboard overview of all platform states.
    POST /orders/sync/{platform}/reset – Force-reset a stuck platform to IDLE.

Order CRUD
    GET  /orders                 – Paginated order list (the dashboard).
    GET  /orders/{order_id}      – Full order detail with line items.
    POST /orders/{order_id}/items – Manually add an order line item.
    PATCH /orders/items/{item_id} – Edit a sales-order line item.
    DELETE /orders/items/{item_id} – Delete a sales-order line item.
    PATCH /orders/{order_id}     – Update order status / notes.

SKU Resolution
    POST /orders/items/{item_id}/match   – Manual match & learn.
    POST /orders/items/{item_id}/confirm – Confirm an auto-match.
    POST /orders/items/{item_id}/reject  – Reject a bad match → UNMATCHED.
"""
import csv
import io
import logging
from pathlib import Path
from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.integrations.amazon.client import AmazonClient
from app.integrations.base import BasePlatformClient, ExternalOrder, ExternalOrderItem
from app.integrations.ebay.client import EbayClient
from app.integrations.ecwid.client import EcwidClient
from app.integrations.walmart.client import WalmartClient
from app.modules.orders.dependencies import (
    get_order_item_repo,
    get_order_repo,
    get_order_sync_service,
    get_sync_repo,
)
from app.modules.orders.models import Order, OrderItem, OrderItemStatus, OrderPlatform, OrderStatus, ShippingStatus
from app.modules.orders.schemas.orders import (
    OrderBrief,
    OrderDetail,
    OrderItemBrief,
    OrderItemCreateRequest,
    OrderItemUpdateRequest,
    OrderItemConfirmRequest,
    OrderItemDetail,
    OrderItemMatchRequest,
    OrderListResponse,
    OrderStatusUpdate,
    ShippingStatusUpdate,
)
from app.modules.orders.schemas.sync import (
    IntegrationStateResponse,
    SalesImportApiRequest,
    SalesImportApiSource,
    SalesImportFileResponse,
    SalesImportFileSource,
    SyncRangeRequest,
    SyncRequest,
    SyncResponse,
    SyncStatusResponse,
)
from app.models.entities import Customer, ProductVariant, ZohoSyncStatus
from app.modules.orders.service import OrderSyncService
from app.repositories.orders.order_repository import OrderItemRepository, OrderRepository
from app.repositories.orders.sync_repository import SyncRepository
from app.api.deps import AdminOrSalesUser, AdminUser

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/orders", tags=["Orders"])

_MARKETPLACE_ZOHO_EXCLUDE_TAX_PLATFORMS = {
    OrderPlatform.AMAZON,
    OrderPlatform.WALMART,
    OrderPlatform.EBAY_MEKONG,
    OrderPlatform.EBAY_USAV,
    OrderPlatform.EBAY_DRAGON,
}


def _to_money_decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except Exception:
        return Decimal("0")


def _quantize_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def _compute_order_totals(order) -> tuple[Decimal, Decimal]:
    line_total = _to_money_decimal(order.subtotal_amount)
    tax = _to_money_decimal(order.tax_amount)
    shipping = _to_money_decimal(order.shipping_amount)
    stored_total = _to_money_decimal(order.total_amount)

    if order.platform in _MARKETPLACE_ZOHO_EXCLUDE_TAX_PLATFORMS:
        inferred_handling = stored_total - (line_total + shipping)
        if inferred_handling < Decimal("0"):
            inferred_handling = Decimal("0")
        platform_total = stored_total if stored_total > Decimal("0") else (line_total + shipping)
        zoho_total = line_total + shipping + inferred_handling
    else:
        inferred_handling = stored_total - (line_total + tax + shipping)
        if inferred_handling < Decimal("0"):
            inferred_handling = Decimal("0")
        platform_total = stored_total if stored_total > Decimal("0") else (line_total + tax + shipping)
        zoho_total = line_total + tax + shipping + inferred_handling

    return _quantize_money(platform_total), _quantize_money(zoho_total)


async def _recalculate_order_totals(db: AsyncSession, order: Order) -> None:
    line_total_raw = (
        await db.execute(
            select(func.coalesce(func.sum(OrderItem.total_price), 0)).where(OrderItem.order_id == order.id)
        )
    ).scalar_one()
    line_total = _to_money_decimal(line_total_raw)

    tax = _to_money_decimal(order.tax_amount)
    shipping = _to_money_decimal(order.shipping_amount)
    previous_subtotal = _to_money_decimal(order.subtotal_amount)
    previous_total = _to_money_decimal(order.total_amount)

    if order.platform in _MARKETPLACE_ZOHO_EXCLUDE_TAX_PLATFORMS:
        inferred_handling = previous_total - (previous_subtotal + shipping)
        if inferred_handling < Decimal("0"):
            inferred_handling = Decimal("0")
        order.subtotal_amount = _quantize_money(line_total)
        order.total_amount = _quantize_money(line_total + shipping + inferred_handling)
        return

    inferred_handling = previous_total - (previous_subtotal + tax + shipping)
    if inferred_handling < Decimal("0"):
        inferred_handling = Decimal("0")

    order.subtotal_amount = _quantize_money(line_total)
    order.total_amount = _quantize_money(line_total + tax + shipping + inferred_handling)

_IMPORT_SOURCE_TO_PLATFORM: dict[SalesImportApiSource, str] = {
    SalesImportApiSource.ECWID: "ECWID",
    SalesImportApiSource.EBAY_MEKONG: "EBAY_MEKONG",
    SalesImportApiSource.EBAY_USAV: "EBAY_USAV",
    SalesImportApiSource.EBAY_DRAGON: "EBAY_DRAGON",
    SalesImportApiSource.WALMART: "WALMART",
}

_PLATFORM_TO_SOURCE: dict[str, str] = {
    "AMAZON": "AMAZON_API",
    "EBAY_MEKONG": "EBAY_MEKONG_API",
    "EBAY_USAV": "EBAY_USAV_API",
    "EBAY_DRAGON": "EBAY_DRAGON_API",
    "ECWID": "ECWID_API",
    "SHOPIFY": "SHOPIFY_API",
    "WALMART": "WALMART_API",
}

_UNMATCHED_EXCEPTIONS_CSV_PATH = Path(__file__).resolve().parents[3] / "misc" / "unmatched_exceptions.csv"


# ============================================================================
# Helper: build platform clients from settings
# ============================================================================

def _build_platform_clients() -> dict[str, BasePlatformClient]:
    """
    Instantiate all configured platform clients.

    Returns a dict keyed by platform_name (matching IntegrationState rows).
    Only clients whose credentials are present are included.
    """
    clients: dict[str, BasePlatformClient] = {}
    logger.debug("Building platform clients from environment variables...")

    # Amazon
    if settings.amazon_client_id:
        clients["AMAZON"] = AmazonClient(
            refresh_token=settings.amazon_refresh_token,
            client_id=settings.amazon_client_id,
            client_secret=settings.amazon_client_secret,
            marketplace_id=settings.amazon_marketplace_id,
        )
        logger.debug("✓ AMAZON client built")
    else:
        logger.debug("✗ AMAZON skipped (amazon_client_id not set)")

    # eBay stores
    ebay_stores = {
        "EBAY_MEKONG": settings.ebay_refresh_token_mekong,
        "EBAY_USAV": settings.ebay_refresh_token_usav,
        "EBAY_DRAGON": settings.ebay_refresh_token_dragon,
    }
    
    # Check shared eBay credentials
    if not settings.ebay_app_id or not settings.ebay_cert_id:
        logger.warning("eBay shared credentials missing (ebay_app_id or ebay_cert_id) - skipping all eBay stores")
    else:
        for store_key, refresh_token in ebay_stores.items():
            if refresh_token:
                store_name = store_key.replace("EBAY_", "")
                clients[store_key] = EbayClient(
                    store_name=store_name,
                    app_id=settings.ebay_app_id,
                    cert_id=settings.ebay_cert_id,
                    refresh_token=refresh_token,
                    sandbox=settings.ebay_sandbox,
                )
                logger.debug(f"✓ {store_key} client built (store_name={store_name})")
            else:
                logger.debug(f"✗ {store_key} skipped (refresh_token not set)")

    # Ecwid
    if settings.ecwid_store_id:
        clients["ECWID"] = EcwidClient(
            store_id=settings.ecwid_store_id,
            access_token=settings.ecwid_secret,
            api_base_url=settings.ecwid_api_base_url,
        )
        logger.debug("✓ ECWID client built")
    else:
        logger.debug("✗ ECWID skipped (ecwid_store_id not set)")

    # Walmart
    if settings.walmart_client_id and settings.walmart_client_secret:
        clients["WALMART"] = WalmartClient(
            client_id=settings.walmart_client_id,
            client_secret=settings.walmart_client_secret,
            api_base_url=settings.walmart_api_base_url,
        )
        logger.debug("WALMART client built")
    else:
        logger.debug("WALMART skipped (walmart credentials not set)")

    logger.debug(f"[DEBUG.INTERNAL_API] Platform clients built: {list(clients.keys())}")
    return clients


class _StaticImportClient(BasePlatformClient):
    def __init__(self, platform_name: str, orders: list):
        self._platform_name = platform_name
        self._orders = orders

    @property
    def platform_name(self) -> str:
        return self._platform_name

    async def authenticate(self) -> bool:
        return True

    async def fetch_orders(self, since=None, until=None, status=None):
        _ = (since, until, status)
        return self._orders

    async def get_order(self, order_id: str):
        _ = order_id
        return None

    async def update_stock(self, updates):
        _ = updates
        return []

    async def update_tracking(self, order_id: str, tracking_number: str, carrier: str) -> bool:
        _ = (order_id, tracking_number, carrier)
        return False


def _parse_order_csv(file_text: str) -> tuple[list[dict], int, int]:
    reader = csv.DictReader(io.StringIO(file_text))
    grouped: dict[str, dict] = {}
    seen = 0
    skipped = 0
    fieldnames = list(reader.fieldnames or [])
    raw_rows: list[dict[str, str]] = []

    def _pick(row_data: dict[str, str], *keys: str) -> str:
        for key in keys:
            value = (row_data.get(key) or "").strip()
            if value:
                return value
        return ""

    def _as_float(row_data: dict[str, str], *keys: str, default: float = 0.0) -> float:
        value = _pick(row_data, *keys)
        if not value:
            return default
        try:
            return float(value)
        except ValueError:
            return default

    def _as_int(row_data: dict[str, str], *keys: str, default: int = 1) -> int:
        value = _pick(row_data, *keys)
        if not value:
            return default
        try:
            parsed = int(float(value))
            return parsed if parsed > 0 else default
        except ValueError:
            return default

    def _normalized(value: str) -> str:
        return (value or "").strip().lower()

    def _address_postal_key(row_data: dict[str, str]) -> tuple[str, str]:
        return (
            _normalized(_pick(row_data, "Ship To - Address 1", "shipping_address_line1")),
            _normalized(_pick(row_data, "Ship To - Postal Code", "shipping_postal_code")),
        )

    def _platform_signal_text(row_data: dict[str, str]) -> str:
        signal_parts = [
            row_data.get("platform"),
            row_data.get("order_platform"),
            row_data.get("Platform"),
            row_data.get("Source Platform"),
            row_data.get("source"),
            row_data.get("Source"),
            row_data.get("order_source"),
            row_data.get("Order Source"),
            row_data.get("Store"),
            row_data.get("Store Name"),
            row_data.get("Advanced Options Source"),
        ]
        return " ".join(str(part or "").strip() for part in signal_parts).upper()

    def _detect_platform(row_data: dict[str, str]) -> str:
        text = _platform_signal_text(row_data)
        if "SHOPIFY" in text:
            return "SHOPIFY"
        if "ECWID" in text:
            return "ECWID"
        if "WALMART" in text:
            return "WALMART"
        if "AMAZON" in text:
            return "AMAZON"
        if "EBAY_USAV" in text:
            return "EBAY_USAV"
        if "EBAY_MEKONG" in text:
            return "EBAY_MEKONG"
        if "EBAY_DRAGON" in text:
            return "EBAY_DRAGON"
        if "EBAY" in text:
            return "EBAY_USAV"
        return "MANUAL"

    def _extract_tracking_number(row_data: dict[str, str]) -> str:
        return _pick(row_data, "tracking_number", "trackingNumber", "Tracking Number", "tracking")

    for row in reader:
        seen += 1
        raw_rows.append({key: (value or "").strip() for key, value in row.items() if key})

    is_shipstation_order_csv = "Order - Number" in fieldnames and "Item - Name" in fieldnames
    valid_rows: list[dict[str, str]] = []

    if is_shipstation_order_csv:
        manual_blank_item_rows: list[dict[str, str]] = []
        for row in raw_rows:
            item_name = _pick(row, "Item - Name")
            if item_name:
                valid_rows.append(row)
            else:
                manual_blank_item_rows.append(row)

        valid_address_postal = {
            _address_postal_key(row)
            for row in valid_rows
            if any(_address_postal_key(row))
        }
        valid_bill_to_names = {
            _normalized(_pick(row, "Bill To - Name", "customer_name"))
            for row in valid_rows
            if _pick(row, "Bill To - Name", "customer_name")
        }

        unmatched_exceptions: list[dict[str, str]] = []
        for row in manual_blank_item_rows:
            matches_parent = False
            addr_postal = _address_postal_key(row)
            if any(addr_postal) and addr_postal in valid_address_postal:
                matches_parent = True
            elif _normalized(_pick(row, "Bill To - Name", "customer_name")) in valid_bill_to_names:
                matches_parent = True

            skipped += 1
            if not matches_parent:
                unmatched_exceptions.append(row)

        _write_unmatched_shipstation_exceptions(fieldnames, unmatched_exceptions)
    else:
        valid_rows = raw_rows

    for row in valid_rows:
        order_number = _pick(row, "Order - Number", "external_order_number", "order_number")
        ext_order_id = order_number or _pick(row, "external_order_id", "order_id", "Order - CustomerID")
        if not ext_order_id:
            skipped += 1
            continue

        quantity = _as_int(row, "Item - Qty", "quantity", "Count - Number of Items", default=1)
        unit_price = _as_float(row, "Item - Price", "unit_price", default=0.0)
        total_price = _as_float(row, "Item - Total", "item_total", "line_total", "Amount - Item Total", "total_price", default=0.0)
        if unit_price == 0.0 or total_price == 0.0:
            subtotal_amount = _as_float(row, "subtotal_amount", "subtotal", "Amount - Order Subtotal", default=0.0)
            total_amount = _as_float(row, "total_amount", "total", "Amount - Order Total", default=0.0)
            if is_shipstation_order_csv:
                if unit_price == 0.0 and total_price > 0.0:
                    unit_price = total_price / quantity if quantity > 0 else 0.0
                if total_price == 0.0:
                    total_price = unit_price * quantity if quantity > 0 else 0.0
            else:
                item_total_fallback = subtotal_amount if subtotal_amount > 0 else total_amount
                if unit_price == 0.0:
                    unit_price = item_total_fallback / quantity if quantity > 0 else 0.0
                if total_price == 0.0:
                    total_price = item_total_fallback if item_total_fallback > 0 else (unit_price * quantity)

        ordered_at = None
        ordered_at_raw = _pick(row, "ordered_at", "Date - Order Date")
        if ordered_at_raw:
            try:
                ordered_at = datetime.fromisoformat(ordered_at_raw.replace("Z", "+00:00"))
            except ValueError:
                try:
                    ordered_at = datetime.strptime(ordered_at_raw, "%m/%d/%Y %I:%M:%S %p")
                except ValueError:
                    ordered_at = None

        platform_name = _detect_platform(row)
        if platform_name == "ECWID":
            skipped += 1
            continue

        group_key = order_number or ext_order_id
        order_entry = grouped.setdefault(
            group_key,
            {
                "platform_name": platform_name,
                "platform_order_id": ext_order_id,
                "platform_order_number": order_number or None,
                "customer_name": _pick(row, "customer_name", "Bill To - Name", "Ship To - Name") or None,
                "customer_email": _pick(row, "customer_email", "Customer Email") or None,
                "ship_address_line1": _pick(row, "shipping_address_line1", "Ship To - Address 1") or None,
                "ship_address_line2": _pick(row, "shipping_address_line2", "Ship To - Address 2") or None,
                "ship_address_line3": _pick(row, "shipping_address_line3", "Ship To - Address 3") or None,
                "ship_city": _pick(row, "shipping_city", "Ship To - City") or None,
                "ship_state": _pick(row, "shipping_state", "Ship To - State") or None,
                "ship_postal_code": _pick(row, "shipping_postal_code", "Ship To - Postal Code") or None,
                "ship_country": _pick(row, "shipping_country", "Ship To - Country") or "US",
                "subtotal": _as_float(row, "subtotal_amount", "subtotal", "Amount - Order Subtotal", default=0.0),
                "tax": _as_float(row, "tax_amount", "tax", "Amount - Order Tax", default=0.0),
                "shipping": _as_float(row, "shipping_amount", "Amount - Shipping Cost", "shipping", "Amount - Order Shipping", default=0.0),
                "handling": _as_float(row, "handling_amount", "handling", "Amount - Handling", "Amount - Handling Cost", default=0.0),
                "total": _as_float(row, "total_amount", "total", "Amount - Order Total", default=0.0),
                "currency": _pick(row, "currency") or "USD",
                "ordered_at": ordered_at,
                "items": [],
                "tracking_number": None,
                "raw_data": {
                    "import_source": "SHIPSTATION_CSV",
                    "platform_name": platform_name,
                    "source": "SHIPSTATION_CSV",
                    "tracking_number": None,
                },
                "_tracking_parts": [],
            },
        )
        tracking_number = _extract_tracking_number(row)
        if tracking_number and tracking_number not in order_entry["_tracking_parts"]:
            order_entry["_tracking_parts"].append(tracking_number)
        if len(order_entry["_tracking_parts"]) == 1:
            merged_tracking = order_entry["_tracking_parts"][0]
        elif len(order_entry["_tracking_parts"]) > 1:
            merged_tracking = " + ".join(order_entry["_tracking_parts"])
        else:
            merged_tracking = None
        order_entry["tracking_number"] = merged_tracking
        order_entry["raw_data"]["tracking_number"] = merged_tracking

        order_entry["items"].append(
            {
                "platform_item_id": _pick(row, "external_item_id", "Order - Number") or None,
                "platform_sku": _pick(row, "Item - SKU", "external_sku", "sku", "SKU") or None,
                "asin": (row.get("external_asin") or "").strip() or None,
                "title": (
                    _pick(row, "Item - Name", "item_name", "title", "Item Name", "Product Name")
                    or "Imported order line"
                ),
                "quantity": quantity,
                "unit_price": unit_price,
                "total_price": total_price,
                "raw_data": row,
            }
        )

    for order_entry in grouped.values():
        # CSV shapes vary; when subtotal is missing, derive line total from item rows.
        line_total = sum(float(item.get("total_price") or 0.0) for item in order_entry.get("items", []))
        subtotal = float(order_entry.get("subtotal") or 0.0)
        tax = float(order_entry.get("tax") or 0.0)
        shipping = float(order_entry.get("shipping") or 0.0)
        handling = float(order_entry.get("handling") or 0.0)
        platform_total = float(order_entry.get("total") or 0.0)

        if subtotal <= 0 and line_total > 0:
            subtotal = line_total
            order_entry["subtotal"] = subtotal

        if platform_total <= 0:
            order_entry["total"] = subtotal + tax + shipping + handling

        order_entry.pop("_tracking_parts", None)

    return list(grouped.values()), seen, skipped


def _write_unmatched_shipstation_exceptions(fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    if not fieldnames:
        return
    try:
        _UNMATCHED_EXCEPTIONS_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _UNMATCHED_EXCEPTIONS_CSV_PATH.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({name: row.get(name, "") for name in fieldnames})
    except Exception:
        logger.exception("Failed to write ShipStation unmatched exceptions CSV")


def _coalesce(value: Optional[str]) -> Optional[str]:
    text = str(value or "").strip()
    return text or None


def _pick_first_nonempty(row: dict[str, str], keys: list[str]) -> Optional[str]:
    for key in keys:
        value = _coalesce(row.get(key))
        if value:
            return value
    return None


def _parse_shipstation_customer_csv(file_text: str) -> tuple[list[dict], int, int]:
    reader = csv.DictReader(io.StringIO(file_text))
    seen = 0
    skipped = 0
    deduped: dict[str, dict] = {}

    for row in reader:
        seen += 1
        email = _pick_first_nonempty(row, ["Customer Email", "Buyer Email"])
        name = _pick_first_nonempty(row, ["Bill To Name", "Ship To Name", "Customer Name"])
        phone = _pick_first_nonempty(row, ["Bill To Phone", "Ship To Phone", "Customer Phone"])
        company = _pick_first_nonempty(row, ["Bill To Company", "Ship To Company", "Company"])

        address_line1 = _pick_first_nonempty(row, ["Bill To Address 1", "Ship To Address 1"])
        address_line2 = _pick_first_nonempty(row, ["Bill To Address 2", "Ship To Address 2"])
        city = _pick_first_nonempty(row, ["Bill To City", "Ship To City"])
        state = _pick_first_nonempty(row, ["Bill To State", "Ship To State"])
        postal_code = _pick_first_nonempty(row, ["Bill To Postal", "Ship To Postal", "Bill To Zip", "Ship To Zip"])
        country = _pick_first_nonempty(row, ["Bill To Country", "Ship To Country", "Ship To Country Code"]) or "US"

        source = (
            _pick_first_nonempty(row, ["Advanced Options Source", "Order Source", "Source"])
            or "SHIPSTATION_CSV"
        )

        if not (email or name or phone):
            skipped += 1
            continue

        dedupe_key = (email or "").lower() or f"{(name or '').lower()}|{(postal_code or '').lower()}"
        existing = deduped.get(dedupe_key)
        if not existing:
            deduped[dedupe_key] = {
                "name": name,
                "email": email,
                "phone": phone,
                "company_name": company,
                "address_line1": address_line1,
                "address_line2": address_line2,
                "city": city,
                "state": state,
                "postal_code": postal_code,
                "country": country,
                "source": source,
            }
            continue

        # Keep the richest row when the same customer appears in multiple orders.
        for key, value in {
            "name": name,
            "email": email,
            "phone": phone,
            "company_name": company,
            "address_line1": address_line1,
            "address_line2": address_line2,
            "city": city,
            "state": state,
            "postal_code": postal_code,
            "country": country,
            "source": source,
        }.items():
            if value and not _coalesce(existing.get(key)):
                existing[key] = value

    return list(deduped.values()), seen, skipped


def _detect_carrier(tracking_number: str) -> str:
    """Smart carrier auto-detection based on length and patterns."""
    t = tracking_number.strip().upper()
    if t.startswith("1Z") and len(t) == 18:
        return "UPS"
    if len(t) == 22 and t.startswith(("91", "92", "93", "94", "95")):
        return "USPS"
    if len(t) == 12 or len(t) == 15:
        return "FedEx"
    return "USPS"  # default fallback


def _parse_tracking_csv(file_text: str) -> tuple[list[dict], int, int]:
    """
    Parse daily Google Sheet tracking summary CSV.
    Columns:
      Col A: Platform
      Col B: Order Number (external_order_id)
      Col I: Tracking (tracking_number)
    """
    reader = csv.reader(io.StringIO(file_text))
    rows_seen = 0
    rows_skipped = 0
    parsed_rows = []

    try:
        header = next(reader)
    except StopIteration:
        return [], 0, 0

    # Locate column indexes by positional headers or fallback to defaults (A=0, B=1, I=8)
    col_platform_idx = 0
    col_order_num_idx = 1
    col_tracking_idx = 8

    # Double check if headers match to adjust indexes
    for idx, col in enumerate(header):
        col_clean = col.strip().lower()
        if "platform" in col_clean:
            col_platform_idx = idx
        elif "order" in col_clean:
            col_order_num_idx = idx
        elif "tracking" in col_clean:
            col_tracking_idx = idx

    for row in reader:
        rows_seen += 1
        if len(row) <= max(col_platform_idx, col_order_num_idx, col_tracking_idx):
            rows_skipped += 1
            continue

        platform = row[col_platform_idx].strip()
        order_number = row[col_order_num_idx].strip()
        tracking = row[col_tracking_idx].strip()

        # Ignore rows that do not have tracking
        if not tracking:
            rows_skipped += 1
            continue

        # Ignore orders that are empty
        if not order_number:
            rows_skipped += 1
            continue

        parsed_rows.append({
            "platform": platform,
            "order_number": order_number,
            "tracking": tracking,
        })

    return parsed_rows, rows_seen, rows_skipped


# ============================================================================
# SYNC ENDPOINTS
# ============================================================================

@router.post("/sync", response_model=list[SyncResponse])
async def sync_orders(
    body: SyncRequest = SyncRequest(),
    service: OrderSyncService = Depends(get_order_sync_service),
):
    """
    **The Smart Trigger.**

    Initiates the Safe-Sync workflow for one or all platforms.
    Returns per-platform results including counts of new orders,
    auto-matched items, and skipped duplicates.
    """
    logger.debug(f"[DEBUG.INTERNAL_API] Sync orders endpoint called: platform={body.platform}")
    clients = _build_platform_clients()
    logger.debug(f"[DEBUG.INTERNAL_API] Available clients: {list(clients.keys())}")

    if body.platform:
        # Single platform
        logger.debug(f"[DEBUG.INTERNAL_API] Single platform sync requested: {body.platform}")
        if body.platform not in clients:
            logger.error(f"Platform '{body.platform}' not in available clients {list(clients.keys())}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Platform '{body.platform}' is not configured or unknown.",
            )
        logger.debug(f"[DEBUG.INTERNAL_API] Starting sync for {body.platform}")
        result = await service.sync_platform(
            body.platform,
            clients[body.platform],
            source=_PLATFORM_TO_SOURCE.get(body.platform, f"{body.platform}_API"),
        )
        logger.info(f"Sync result for {body.platform}: success={result.success}, new={result.new_orders}, errors={result.errors}")
        return [result]

    # All platforms
    logger.debug(f"[DEBUG.INTERNAL_API] Syncing all platforms: {list(clients.keys())}")
    results: list[SyncResponse] = []
    for name, client in clients.items():
        logger.debug(f"[DEBUG.INTERNAL_API] Starting sync for platform: {name}")
        result = await service.sync_platform(
            name,
            client,
            source=_PLATFORM_TO_SOURCE.get(name, f"{name}_API"),
        )
        logger.info(f"Sync result for {name}: success={result.success}, new={result.new_orders}, errors={result.errors}")
        results.append(result)

    logger.info(f"All platform sync complete: {len(results)} results")
    return results


@router.post("/sync/range", response_model=list[SyncResponse])
async def sync_orders_range(
    body: SyncRangeRequest,
    _admin: AdminUser,
    service: OrderSyncService = Depends(get_order_sync_service),
):
    """
    **Admin-only: Sync orders within a custom date range.**

    Allows administrators to fetch historical orders from platforms
    between ``since`` and ``until`` timestamps. Does *not* acquire
    a sync lock or update the last-sync anchor. Duplicate orders are
    still safely skipped.
    """
    logger.debug(
        "[DEBUG.INTERNAL_API] Admin range sync: platform=%s  since=%s  until=%s",
        body.platform, body.since.isoformat(), body.until.isoformat(),
    )
    clients = _build_platform_clients()

    if body.platform:
        if body.platform not in clients:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Platform '{body.platform}' is not configured or unknown.",
            )
        result = await service.sync_platform_range(
            body.platform,
            clients[body.platform],
            body.since,
            body.until,
            source=_PLATFORM_TO_SOURCE.get(body.platform, f"{body.platform}_API"),
        )
        return [result]

    results: list[SyncResponse] = []
    for name, client in clients.items():
        result = await service.sync_platform_range(
            name,
            client,
            body.since,
            body.until,
            source=_PLATFORM_TO_SOURCE.get(name, f"{name}_API"),
        )
        results.append(result)

    return results


@router.post("/sync/refresh-matching", response_model=dict[str, int])
async def refresh_unmatched_item_matching(
    _admin: AdminUser,
    service: OrderSyncService = Depends(get_order_sync_service),
    db: AsyncSession = Depends(get_db),
):
    """
    Admin-only bulk rematch pass for unmatched sales-order items.

    For each UNMATCHED item:
    1) Match by exact external_item_id against PLATFORM_LISTING.external_ref_id.
    2) Fallback to exact listing name match.
    """
    summary = await service.refresh_unmatched_item_matches()
    await db.commit()
    return summary


@router.get("/sync/status", response_model=SyncStatusResponse)
async def sync_status(
    sync_repo: SyncRepository = Depends(get_sync_repo),
    order_item_repo: OrderItemRepository = Depends(get_order_item_repo),
    order_repo: OrderRepository = Depends(get_order_repo),
):
    """
    Dashboard overview: platform states + aggregate item counters.
    """
    states = await sync_repo.get_all_states()
    status_counts = await order_item_repo.count_by_status()
    _, total_orders = await order_repo.list_orders(limit=0)

    return SyncStatusResponse(
        platforms=[IntegrationStateResponse.model_validate(s) for s in states],
        total_orders=total_orders,
        total_unmatched_items=status_counts.get("UNMATCHED", 0),
        total_matched_items=status_counts.get("MATCHED", 0),
    )


@router.post("/sync/{platform_name}/reset", response_model=IntegrationStateResponse)
async def reset_sync_state(
    platform_name: str,
    sync_repo: SyncRepository = Depends(get_sync_repo),
    db: AsyncSession = Depends(get_db),
):
    """Force-reset a platform from ERROR/SYNCING back to IDLE."""
    state = await sync_repo.get_by_platform(platform_name)
    if state is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No integration state for '{platform_name}'.",
        )
    await sync_repo.reset_to_idle(platform_name)
    await db.commit()
    updated = await sync_repo.get_by_platform(platform_name)
    return IntegrationStateResponse.model_validate(updated)


@router.post("/import/api", response_model=SyncResponse)
async def import_orders_from_api(
    body: SalesImportApiRequest,
    _staff: AdminOrSalesUser,
    service: OrderSyncService = Depends(get_order_sync_service),
):
    clients = _build_platform_clients()
    platform_name = _IMPORT_SOURCE_TO_PLATFORM[body.source]
    if platform_name not in clients:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Platform '{platform_name}' is not configured or unknown.",
        )

    return await service.sync_platform_range(
        platform_name,
        clients[platform_name],
        body.since,
        body.until,
        source=_PLATFORM_TO_SOURCE.get(platform_name, f"{platform_name}_API"),
    )


@router.post("/import/file", response_model=SalesImportFileResponse)
async def import_orders_from_file(
    _staff: AdminOrSalesUser,
    source: Annotated[SalesImportFileSource, Query()],
    file: UploadFile = File(...),
    service: OrderSyncService = Depends(get_order_sync_service),
    db: AsyncSession = Depends(get_db),
):
    if source not in {SalesImportFileSource.CSV_GENERIC, SalesImportFileSource.SHIPSTATION_CUSTOMER_CSV, SalesImportFileSource.TRACKING_CSV}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported import source",
        )

    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only CSV file uploads are supported.",
        )

    content = await file.read()
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CSV must be UTF-8 encoded.",
        ) from exc

    if source == SalesImportFileSource.TRACKING_CSV:
        rows, rows_seen, rows_skipped = _parse_tracking_csv(text)
        updated_count = 0
        skipped_duplicates = 0
        errors = []

        for row in rows:
            order_number = row["order_number"]
            tracking = row["tracking"]
            platform_str = row["platform"]

            # Uniqueness check: is this tracking number already assigned to another order in the database?
            val = tracking.strip()
            # Fetch matching order(s) by external_order_id or external_order_number
            stmt = select(Order).where(
                (Order.external_order_id == order_number) | (Order.external_order_number == order_number)
            )
            orders = (await db.execute(stmt)).scalars().all()

            if not orders:
                # Silently ignore orders that cannot be found
                rows_skipped += 1
                continue

            # If there are multiple matches (e.g. across platforms), try to match the platform string if available
            order = None
            if len(orders) > 1 and platform_str:
                platform_lower = platform_str.strip().lower()
                for o in orders:
                    if platform_lower in o.platform.value.lower():
                        order = o
                        break
            if not order:
                order = orders[0]

            # Verify tracking uniqueness
            stmt_uniq = select(Order).where(
                func.lower(Order.tracking_number) == func.lower(val),
                Order.id != order.id
            )
            duplicate_order = (await db.execute(stmt_uniq)).scalars().first()
            if duplicate_order:
                # Skip duplicate and record error/warning to prevent 2 trackings in the system
                msg = f"Tracking '{tracking}' for order '{order_number}' already assigned to order '{duplicate_order.external_order_id}'."
                logger.warning(msg)
                errors.append(msg)
                skipped_duplicates += 1
                continue

            # Detect carrier
            carrier = _detect_carrier(tracking)

            # Update tracking and status
            order.tracking_number = tracking
            order.carrier = carrier
            order.status = OrderStatus.SHIPPED
            order.shipping_status = ShippingStatus.SHIPPING
            order.zoho_sync_status = ZohoSyncStatus.DIRTY
            db.add(order)
            updated_count += 1

        await db.commit()

        return SalesImportFileResponse(
            source=source,
            source_rows_seen=rows_seen,
            source_rows_skipped=rows_skipped,
            customers_created=0,
            customers_updated=0,
            new_orders=updated_count,
            new_items=0,
            auto_matched=0,
            skipped_duplicates=skipped_duplicates,
            success=True,  # Return success True even if some are skipped/errors, matching sync behavior
            errors=errors,
        )

    if source == SalesImportFileSource.SHIPSTATION_CUSTOMER_CSV:
        customers, rows_seen, rows_skipped = _parse_shipstation_customer_csv(text)
        created = 0
        updated = 0

        for payload in customers:
            email = _coalesce(payload.get("email"))
            name = _coalesce(payload.get("name"))
            postal_code = _coalesce(payload.get("postal_code"))
            phone = _coalesce(payload.get("phone"))
            source_value = _coalesce(payload.get("source")) or "SHIPSTATION_CSV"

            customer: Optional[Customer] = None

            if email:
                existing = await db.execute(select(Customer).where(Customer.email == email))
                customer = existing.scalar_one_or_none()

            if customer is None and name:
                query = select(Customer).where(Customer.name == name)
                if postal_code:
                    query = query.where(Customer.postal_code == postal_code)
                existing = await db.execute(query)
                customer = existing.scalar_one_or_none()

            if customer is None and phone:
                existing = await db.execute(select(Customer).where(Customer.phone == phone))
                customer = existing.scalar_one_or_none()

            if customer is None:
                customer = Customer(
                    name=name or "Unknown",
                    email=email,
                    phone=phone,
                    company_name=_coalesce(payload.get("company_name")),
                    address_line1=_coalesce(payload.get("address_line1")),
                    address_line2=_coalesce(payload.get("address_line2")),
                    city=_coalesce(payload.get("city")),
                    state=_coalesce(payload.get("state")),
                    postal_code=postal_code,
                    country=_coalesce(payload.get("country")) or "US",
                    source=source_value,
                    is_active=True,
                )
                db.add(customer)
                created += 1
                continue

            changed = False
            if name and (not _coalesce(customer.name) or customer.name == "Unknown"):
                customer.name = name
                changed = True
            if email and not _coalesce(customer.email):
                customer.email = email
                changed = True
            if phone and not _coalesce(customer.phone):
                customer.phone = phone
                changed = True
            if _coalesce(payload.get("company_name")) and not _coalesce(customer.company_name):
                customer.company_name = _coalesce(payload.get("company_name"))
                changed = True
            if _coalesce(payload.get("address_line1")) and not _coalesce(customer.address_line1):
                customer.address_line1 = _coalesce(payload.get("address_line1"))
                changed = True
            if _coalesce(payload.get("address_line2")) and not _coalesce(customer.address_line2):
                customer.address_line2 = _coalesce(payload.get("address_line2"))
                changed = True
            if _coalesce(payload.get("city")) and not _coalesce(customer.city):
                customer.city = _coalesce(payload.get("city"))
                changed = True
            if _coalesce(payload.get("state")) and not _coalesce(customer.state):
                customer.state = _coalesce(payload.get("state"))
                changed = True
            if postal_code and not _coalesce(customer.postal_code):
                customer.postal_code = postal_code
                changed = True
            if _coalesce(payload.get("country")) and not _coalesce(customer.country):
                customer.country = _coalesce(payload.get("country"))
                changed = True
            if source_value != customer.source:
                customer.source = source_value
                changed = True

            if changed:
                db.add(customer)
                updated += 1

        await db.commit()

        return SalesImportFileResponse(
            source=source,
            source_rows_seen=rows_seen,
            source_rows_skipped=rows_skipped,
            customers_created=created,
            customers_updated=updated,
            new_orders=0,
            new_items=0,
            auto_matched=0,
            skipped_duplicates=0,
            success=True,
            errors=[],
        )

    rows, rows_seen, rows_skipped = _parse_order_csv(text)
    orders_by_platform: dict[str, list[ExternalOrder]] = {}
    for row in rows:
        items = [
            ExternalOrderItem(
                platform_item_id=item["platform_item_id"],
                platform_sku=item["platform_sku"],
                asin=item["asin"],
                title=item["title"],
                quantity=item["quantity"],
                unit_price=item["unit_price"],
                total_price=item["total_price"],
                raw_data=item["raw_data"],
            )
            for item in row["items"]
        ]
        platform_name = row.get("platform_name") or "MANUAL"
        external_order = ExternalOrder(
            platform_order_id=row["platform_order_id"],
            platform_order_number=row["platform_order_number"],
            customer_name=row["customer_name"],
            customer_email=row["customer_email"],
            ship_address_line1=row["ship_address_line1"],
            ship_address_line2=row["ship_address_line2"],
            ship_address_line3=row["ship_address_line3"],
            ship_city=row["ship_city"],
            ship_state=row["ship_state"],
            ship_postal_code=row["ship_postal_code"],
            ship_country=row["ship_country"],
            subtotal=row["subtotal"],
            tax=row["tax"],
            shipping=row["shipping"],
            total=row["total"],
            currency=row["currency"],
            ordered_at=row["ordered_at"],
            items=items,
            raw_data=row["raw_data"],
            customer_source=None,
            tracking_number=row.get("tracking_number"),
        )
        orders_by_platform.setdefault(platform_name, []).append(external_order)
    aggregate = {
        "new_orders": 0,
        "new_items": 0,
        "auto_matched": 0,
        "skipped_duplicates": 0,
        "errors": [],
        "success": True,
    }
    for platform_name, platform_orders in orders_by_platform.items():
        client = _StaticImportClient(platform_name, platform_orders)
        result = await service.sync_platform_range(
            platform_name,
            client,
            datetime(1970, 1, 1, tzinfo=timezone.utc),
            datetime.now(timezone.utc),
            source="SHIPSTATION_CSV",
        )
        aggregate["new_orders"] += result.new_orders
        aggregate["new_items"] += result.new_items
        aggregate["auto_matched"] += result.auto_matched
        aggregate["skipped_duplicates"] += result.skipped_duplicates
        aggregate["errors"].extend(result.errors)
        if not result.success:
            aggregate["success"] = False

    return SalesImportFileResponse(
        source=source,
        source_rows_seen=rows_seen,
        source_rows_skipped=rows_skipped,
        new_orders=aggregate["new_orders"],
        new_items=aggregate["new_items"],
        auto_matched=aggregate["auto_matched"],
        skipped_duplicates=aggregate["skipped_duplicates"],
        success=aggregate["success"],
        errors=aggregate["errors"],
    )


# ============================================================================
# ORDER CRUD ENDPOINTS
# ============================================================================

@router.get("", response_model=OrderListResponse)
async def list_orders(
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    platform: Annotated[Optional[OrderPlatform], Query()] = None,
    status_filter: Annotated[Optional[str], Query(alias="status")] = None,
    item_status: Annotated[Optional[OrderItemStatus], Query()] = None,
    ordered_at_from: Annotated[Optional[datetime], Query()] = None,
    ordered_at_to: Annotated[Optional[datetime], Query()] = None,
    zoho_sync_status: Annotated[Optional[str], Query()] = None,
    source: Annotated[Optional[str], Query()] = None,
    sort_by: Annotated[str, Query(pattern="^(ordered_at|created_at|total_amount|external_order_id)$")] = "ordered_at",
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "desc",
    search: Annotated[Optional[str], Query()] = None,
    order_repo: OrderRepository = Depends(get_order_repo),
):
    """
    **The Dashboard.**

    Paginated order list with optional filters for platform, status,
    item-level status (e.g. UNMATCHED), and free-text search.
    """
    from app.modules.orders.models import OrderStatus as OS
    from app.models.entities import ZohoSyncStatus as ZS

    os_filter = None
    zs_filter = None
    if status_filter:
        try:
            os_filter = OS(status_filter)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid order status: {status_filter}",
            )
    if zoho_sync_status:
        try:
            zs_filter = ZS(zoho_sync_status)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid Zoho sync status: {zoho_sync_status}",
            )

    orders, total = await order_repo.list_orders(
        skip=skip,
        limit=limit,
        platform=platform,
        status=os_filter,
        item_status=item_status,
        ordered_at_from=ordered_at_from,
        ordered_at_to=ordered_at_to,
        zoho_sync_status=zs_filter,
        source=source,
        sort_by=sort_by,
        sort_dir=sort_dir,
        search=search,
    )

    briefs = []
    for o in orders:
        raw_items = o.items if o.items else []
        if isinstance(raw_items, list):
            items = raw_items
        else:
            items = [raw_items]
        
        platform_total_amount, zoho_total_amount = _compute_order_totals(o)

        briefs.append(
            OrderBrief(
                id=o.id,
                platform=o.platform,
                source=o.source,
                external_order_id=o.external_order_id,
                external_order_number=o.external_order_number,
                status=o.status,
                shipping_status=o.shipping_status,
                zoho_sync_status=o.zoho_sync_status,
                customer_name=o.customer_name,
                tracking_number=o.tracking_number,
                subtotal_amount=o.subtotal_amount,
                tax_amount=o.tax_amount,
                shipping_amount=o.shipping_amount,
                total_amount=o.total_amount,
                platform_total_amount=platform_total_amount,
                zoho_total_amount=zoho_total_amount,
                currency=o.currency,
                ordered_at=o.ordered_at,
                created_at=o.created_at,
                item_count=len(items),
                unmatched_count=sum(
                    1 for i in items if i.status == OrderItemStatus.UNMATCHED
                ),
            )
        )

    return OrderListResponse(total=total, skip=skip, limit=limit, items=briefs)


@router.get("/{order_id}", response_model=OrderDetail)
async def get_order(
    order_id: int,
    order_repo: OrderRepository = Depends(get_order_repo),
):
    """**Order Detail:** Full view of header and all line items."""
    order = await order_repo.get_with_items(order_id)
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order {order_id} not found.",
        )
    platform_total_amount, zoho_total_amount = _compute_order_totals(order)
    detail = OrderDetail.model_validate(order)
    detail.platform_total_amount = platform_total_amount
    detail.zoho_total_amount = zoho_total_amount
    return detail


@router.post(
    "/{order_id}/items",
    response_model=OrderItemDetail,
    status_code=status.HTTP_201_CREATED,
)
async def add_order_item(
    order_id: int,
    body: OrderItemCreateRequest,
    order_repo: OrderRepository = Depends(get_order_repo),
    order_item_repo: OrderItemRepository = Depends(get_order_item_repo),
    db: AsyncSession = Depends(get_db),
):
    order = await order_repo.get(order_id)
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order {order_id} not found.",
        )

    if body.variant_id is not None:
        variant = await db.get(ProductVariant, body.variant_id)
        if variant is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"ProductVariant {body.variant_id} not found.",
            )

    created = await order_item_repo.create(
        {
            "order_id": order_id,
            "external_item_id": body.external_item_id,
            "external_sku": body.external_sku,
            "variant_id": body.variant_id,
            "status": OrderItemStatus.MATCHED if body.variant_id is not None else OrderItemStatus.UNMATCHED,
            "item_name": body.item_name,
            "quantity": body.quantity,
            "unit_price": body.unit_price,
            "total_price": body.total_price,
        }
    )
    order.zoho_sync_status = ZohoSyncStatus.DIRTY
    await _recalculate_order_totals(db, order)

    await db.commit()
    await db.refresh(created)
    return OrderItemDetail.model_validate(created)


@router.patch(
    "/items/{item_id}",
    response_model=OrderItemDetail,
)
async def update_order_item(
    item_id: int,
    body: OrderItemUpdateRequest,
    order_item_repo: OrderItemRepository = Depends(get_order_item_repo),
    db: AsyncSession = Depends(get_db),
):
    item = await order_item_repo.get(item_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"OrderItem {item_id} not found.",
        )

    if body.variant_id is not None:
        variant = await db.get(ProductVariant, body.variant_id)
        if variant is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"ProductVariant {body.variant_id} not found.",
            )

    if body.external_item_id is not None:
        item.external_item_id = body.external_item_id or None
    if body.external_sku is not None:
        item.external_sku = body.external_sku or None
    if body.item_name is not None:
        item.item_name = body.item_name
    if body.quantity is not None:
        item.quantity = body.quantity
    if body.unit_price is not None:
        item.unit_price = body.unit_price
    if body.total_price is not None:
        item.total_price = body.total_price
    if body.variant_id is not None:
        item.variant_id = body.variant_id
        item.status = OrderItemStatus.MATCHED

    order = await db.get(Order, item.order_id)
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order {item.order_id} not found.",
        )

    order.zoho_sync_status = ZohoSyncStatus.DIRTY
    await _recalculate_order_totals(db, order)
    await db.commit()
    await db.refresh(item)
    return OrderItemDetail.model_validate(item)


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_order_item(
    item_id: int,
    order_item_repo: OrderItemRepository = Depends(get_order_item_repo),
    db: AsyncSession = Depends(get_db),
):
    item = await order_item_repo.get(item_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"OrderItem {item_id} not found.",
        )

    order = await db.get(Order, item.order_id)
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order {item.order_id} not found.",
        )

    await order_item_repo.delete(item_id)
    order.zoho_sync_status = ZohoSyncStatus.DIRTY
    await _recalculate_order_totals(db, order)
    await db.commit()


@router.patch("/{order_id}", response_model=OrderDetail)
async def update_order_status(
    order_id: int,
    body: OrderStatusUpdate,
    order_repo: OrderRepository = Depends(get_order_repo),
    db: AsyncSession = Depends(get_db),
):
    """Update an order's processing status and/or notes."""
    order = await order_repo.get_with_items(order_id)
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order {order_id} not found.",
        )

    # Enforce that any order marked as SHIPPED or DELIVERED must have a tracking number
    if body.status in {OrderStatus.SHIPPED, OrderStatus.DELIVERED}:
        if not order.tracking_number:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Tracking number is required when setting status to SHIPPED or DELIVERED."
            )

    update_data: dict = {"status": body.status}
    if body.notes is not None:
        update_data["processing_notes"] = body.notes

    updated = await order_repo.update(order, update_data)
    await db.commit()
    await db.refresh(updated)
    return OrderDetail.model_validate(updated)


@router.patch("/{order_id}/shipping", response_model=OrderDetail)
async def update_shipping_status(
    order_id: int,
    body: ShippingStatusUpdate,
    order_repo: OrderRepository = Depends(get_order_repo),
    db: AsyncSession = Depends(get_db),
):
    """
    Update an order's shipping / fulfilment status.

    Side-effects:
    - Marks ``zoho_sync_status`` as DIRTY so the next outbound sync
      pushes package / shipment changes to Zoho.
    - When status is PACKED or SHIPPING, the Zoho sync will create a
      package (marking the sales order as packed).
    - When status is DELIVERED, the Zoho sync will mark the shipment
      as delivered / fulfilled.
    """
    from app.models.entities import ZohoSyncStatus

    order = await order_repo.get_with_items(order_id)
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order {order_id} not found.",
        )

    # Enforce uniqueness of tracking number
    if body.tracking_number is not None:
        val = body.tracking_number.strip()
        if val:
            stmt = select(Order).where(
                func.lower(Order.tracking_number) == func.lower(val),
                Order.id != order_id
            )
            duplicate_order = (await db.execute(stmt)).scalars().first()
            if duplicate_order:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Tracking number '{body.tracking_number}' is already assigned to order '{duplicate_order.external_order_id}'."
                )

    # Enforce tracking presence when setting shipping status to SHIPPING or DELIVERED
    new_shipping_status = body.shipping_status
    effective_tracking = (body.tracking_number or "").strip() or (order.tracking_number or "").strip()
    if new_shipping_status in {ShippingStatus.SHIPPING, ShippingStatus.DELIVERED} and not effective_tracking:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tracking number is required when setting shipping status to SHIPPING or DELIVERED."
        )

    update_data: dict = {"shipping_status": body.shipping_status}

    # Persist optional tracking info
    if body.tracking_number is not None:
        update_data["tracking_number"] = body.tracking_number
    if body.carrier is not None:
        update_data["carrier"] = body.carrier
    if body.notes is not None:
        update_data["processing_notes"] = body.notes

    # Mark Zoho sync as dirty so the outbound sync picks up the change
    if order.shipping_status != body.shipping_status:
        update_data["zoho_sync_status"] = ZohoSyncStatus.DIRTY

    updated = await order_repo.update(order, update_data)
    await db.commit()
    await db.refresh(updated)
    return OrderDetail.model_validate(updated)


@router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_order(
    order_id: int,
    _admin: AdminUser,
    order_repo: OrderRepository = Depends(get_order_repo),
    db: AsyncSession = Depends(get_db),
):
    """Admin-only hard delete for an order and its line items."""
    order = await order_repo.get(order_id)
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order {order_id} not found.",
        )

    await order_repo.delete(order_id)
    await db.commit()


# ============================================================================
# SKU RESOLUTION ENDPOINTS
# ============================================================================

@router.post(
    "/items/{item_id}/match",
    response_model=OrderItemDetail,
    status_code=status.HTTP_200_OK,
)
async def match_order_item(
    item_id: int,
    body: OrderItemMatchRequest,
    service: OrderSyncService = Depends(get_order_sync_service),
    db: AsyncSession = Depends(get_db),
):
    """
    **The Fix & Learn.**

    Links an order item to an internal product variant. If ``learn=True``
    (default), also creates a ``PLATFORM_LISTING`` row so the auto-match
    engine can recognise this external ID in future syncs.
    """
    try:
        item = await service.match_item(
            item_id,
            body.variant_id,
            learn=body.learn,
            notes=body.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    await db.commit()
    await db.refresh(item)
    return OrderItemDetail.model_validate(item)


@router.post(
    "/items/{item_id}/confirm",
    response_model=OrderItemDetail,
)
async def confirm_order_item(
    item_id: int,
    body: OrderItemConfirmRequest = OrderItemConfirmRequest(),
    service: OrderSyncService = Depends(get_order_sync_service),
    db: AsyncSession = Depends(get_db),
):
    """**The Verification:** Confirms an AUTO_ASSIGNED match."""
    try:
        item = await service.confirm_item(item_id, notes=body.notes)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc),
        )

    await db.commit()
    await db.refresh(item)
    return OrderItemDetail.model_validate(item)


@router.post(
    "/items/{item_id}/reject",
    response_model=OrderItemDetail,
)
async def reject_order_item(
    item_id: int,
    service: OrderSyncService = Depends(get_order_sync_service),
    db: AsyncSession = Depends(get_db),
):
    """
    **The Correction:** Rejects a bad match, resetting status to UNMATCHED.
    """
    try:
        item = await service.reject_item(item_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc),
        )

    await db.commit()
    await db.refresh(item)
    return OrderItemDetail.model_validate(item)
