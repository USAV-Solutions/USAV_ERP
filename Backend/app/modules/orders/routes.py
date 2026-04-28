"""
Order module API routes.

Endpoints
---------
Synchronization
    POST /orders/sync            – Trigger "Safe Sync" for one or all platforms.
    GET  /orders/sync/status     – Dashboard overview of all platform states.
    POST /orders/sync/{platform}/reset – Force-reset a stuck platform to IDLE.

Order CRUD
    GET  /orders                 – Paginated order list (the dashboard).
    GET  /orders/{order_id}      – Full order detail with line items.
    PATCH /orders/{order_id}     – Update order status / notes.

SKU Resolution
    POST /orders/items/{item_id}/match   – Manual match & learn.
    POST /orders/items/{item_id}/confirm – Confirm an auto-match.
    POST /orders/items/{item_id}/reject  – Reject a bad match → UNMATCHED.
"""
import csv
import io
import logging
from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import select
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
from app.modules.orders.models import OrderItemStatus, OrderPlatform, ShippingStatus
from app.modules.orders.schemas.orders import (
    OrderBrief,
    OrderDetail,
    OrderItemBrief,
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
from app.models.entities import Customer
from app.modules.orders.service import OrderSyncService
from app.repositories.orders.order_repository import OrderItemRepository, OrderRepository
from app.repositories.orders.sync_repository import SyncRepository
from app.api.deps import AdminOrSalesUser, AdminUser

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/orders", tags=["Orders"])

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
    "WALMART": "WALMART_API",
}


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

    for row in reader:
        seen += 1
        ext_order_id = (row.get("external_order_id") or row.get("order_id") or "").strip()
        item_name = (row.get("item_name") or row.get("title") or "").strip()
        if not ext_order_id or not item_name:
            skipped += 1
            continue

        external_item_id = (row.get("external_item_id") or "").strip() or None
        external_sku = (row.get("external_sku") or row.get("sku") or "").strip() or None
        quantity_text = (row.get("quantity") or "1").strip()
        unit_price_text = (row.get("unit_price") or "0").strip()
        total_price_text = (row.get("total_price") or "").strip()

        try:
            quantity = int(quantity_text)
            unit_price = float(unit_price_text)
            total_price = float(total_price_text) if total_price_text else unit_price * quantity
        except ValueError:
            skipped += 1
            continue

        ordered_at = None
        ordered_at_raw = (row.get("ordered_at") or "").strip()
        if ordered_at_raw:
            try:
                ordered_at = datetime.fromisoformat(ordered_at_raw.replace("Z", "+00:00"))
            except ValueError:
                ordered_at = None

        order_entry = grouped.setdefault(
            ext_order_id,
            {
                "platform_order_id": ext_order_id,
                "platform_order_number": (row.get("external_order_number") or row.get("order_number") or "").strip() or None,
                "customer_name": (row.get("customer_name") or "").strip() or None,
                "customer_email": (row.get("customer_email") or "").strip() or None,
                "ship_address_line1": (row.get("shipping_address_line1") or "").strip() or None,
                "ship_address_line2": (row.get("shipping_address_line2") or "").strip() or None,
                "ship_city": (row.get("shipping_city") or "").strip() or None,
                "ship_state": (row.get("shipping_state") or "").strip() or None,
                "ship_postal_code": (row.get("shipping_postal_code") or "").strip() or None,
                "ship_country": (row.get("shipping_country") or "").strip() or "US",
                "subtotal": float((row.get("subtotal_amount") or row.get("subtotal") or "0").strip() or "0"),
                "tax": float((row.get("tax_amount") or row.get("tax") or "0").strip() or "0"),
                "shipping": float((row.get("shipping_amount") or row.get("shipping") or "0").strip() or "0"),
                "total": float((row.get("total_amount") or row.get("total") or "0").strip() or "0"),
                "currency": (row.get("currency") or "USD").strip() or "USD",
                "ordered_at": ordered_at,
                "items": [],
                "raw_data": {"import_source": "CSV_GENERIC"},
            },
        )

        order_entry["items"].append(
            {
                "platform_item_id": external_item_id,
                "platform_sku": external_sku,
                "asin": (row.get("external_asin") or "").strip() or None,
                "title": item_name,
                "quantity": quantity,
                "unit_price": unit_price,
                "total_price": total_price,
                "raw_data": row,
            }
        )

    return list(grouped.values()), seen, skipped


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
    if source not in {SalesImportFileSource.CSV_GENERIC, SalesImportFileSource.SHIPSTATION_CUSTOMER_CSV}:
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
    external_orders: list[ExternalOrder] = []
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
        external_orders.append(
            ExternalOrder(
                platform_order_id=row["platform_order_id"],
                platform_order_number=row["platform_order_number"],
                customer_name=row["customer_name"],
                customer_email=row["customer_email"],
                ship_address_line1=row["ship_address_line1"],
                ship_address_line2=row["ship_address_line2"],
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
            )
        )

    client = _StaticImportClient("MANUAL", external_orders)
    result = await service.sync_platform_range(
        "MANUAL",
        client,
        datetime(1970, 1, 1, tzinfo=timezone.utc),
        datetime.now(timezone.utc),
        source=source.value,
    )

    return SalesImportFileResponse(
        source=source,
        source_rows_seen=rows_seen,
        source_rows_skipped=rows_skipped,
        new_orders=result.new_orders,
        new_items=result.new_items,
        auto_matched=result.auto_matched,
        skipped_duplicates=result.skipped_duplicates,
        success=result.success,
        errors=result.errors,
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
                total_amount=o.total_amount,
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
    return OrderDetail.model_validate(order)


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
