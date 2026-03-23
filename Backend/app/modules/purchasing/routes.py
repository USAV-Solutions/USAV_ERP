"""API routes for purchasing module."""
import csv
import io
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminOrWarehouseUser, CurrentUser
from app.core.database import get_db
from app.integrations.zoho.client import ZohoClient
from app.models import PurchaseDeliverStatus, PurchaseOrderItemStatus, ZohoSyncStatus
from app.models.entities import ProductVariant
from app.models.purchasing import PurchaseOrder, PurchaseOrderItem
from app.modules.purchasing.dependencies import (
    get_purchase_order_item_repo,
    get_purchase_order_repo,
    get_purchasing_service,
    get_vendor_repo,
)
from app.modules.purchasing.schemas import (
    GoodwillCsvImportResponse,
    PurchaseFileImportResponse,
    PurchaseFileImportSource,
    PurchaseOrderCreate,
    PurchaseOrderItemCreate,
    PurchaseOrderItemMatchRequest,
    PurchaseOrderItemResponse,
    PurchaseOrderItemUpdate,
    PurchaseOrderReceiveRequest,
    PurchaseOrderReceiveResponse,
    PurchaseOrderResponse,
    VendorCreate,
    VendorResponse,
    VendorUpdate,
    ZohoPurchaseImportResponse,
)
from app.modules.purchasing.service import PurchasingService
from app.repositories.purchasing import (
    PurchaseOrderItemRepository,
    PurchaseOrderRepository,
    VendorRepository,
)
from app.repositories.product import ProductVariantRepository

router = APIRouter(tags=["Purchasing"])


def _to_decimal(value: object, default: str = "0") -> Decimal:
    try:
        text = str(value if value is not None else default)
        normalized = text.replace("$", "").replace(",", "").strip()
        if normalized == "":
            normalized = default
        return Decimal(normalized)
    except Exception:
        return Decimal(default)


def _to_date(value: object) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        text = value.strip()
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            for fmt in ("%m/%d/%Y", "%m/%d/%y", "%b %d, %Y", "%B %d, %Y"):
                try:
                    return datetime.strptime(text, fmt).date()
                except ValueError:
                    continue
    return date.today()


def _to_date_or_none(value: object) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        text = value.strip()
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            for fmt in ("%m/%d/%Y", "%m/%d/%y", "%b %d, %Y", "%B %d, %Y"):
                try:
                    return datetime.strptime(text, fmt).date()
                except ValueError:
                    continue
    return None


def _resolve_zoho_external_item_name(existing_name: str | None) -> str:
    """Use preserved local naming and never source line names from Zoho payload."""
    preserved_name = str(existing_name or "").strip()
    if preserved_name:
        return preserved_name[:255]

    return "Imported Item"


def _decode_upload_text(raw: bytes) -> str:
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def _normalize_currency(value: object) -> str:
    currency_text = str(value or "").strip().upper()
    aliases = {
        "$": "USD",
        "US$": "USD",
        "USD": "USD",
        "EUR": "EUR",
        "€": "EUR",
        "GBP": "GBP",
        "£": "GBP",
    }
    if currency_text in aliases:
        return aliases[currency_text]
    if len(currency_text) >= 3 and currency_text[:3].isalpha():
        return currency_text[:3]
    return "USD"


def _normalize_custom_field_key(value: object) -> str:
    text = str(value or "").strip().lower().replace(" ", "_")
    return text


def _build_custom_field_aliases(*keys: str) -> set[str]:
    aliases: set[str] = set()
    for raw in keys:
        key = _normalize_custom_field_key(raw)
        if not key:
            continue
        aliases.add(key)
        if key.startswith("cf_"):
            aliases.add(key[3:])
        else:
            aliases.add(f"cf_{key}")
    return aliases


def _to_int(value: object, default: int = 0) -> int:
    try:
        text = str(value if value is not None else default).replace(",", "").strip()
        if text == "":
            return default
        return int(Decimal(text))
    except Exception:
        return default


def _build_purchase_item_link(source: PurchaseFileImportSource, *, asin: str | None = None, item_id: str | None = None) -> str | None:
    normalized_asin = str(asin or "").strip()
    normalized_item_id = str(item_id or "").strip()

    if source == PurchaseFileImportSource.AMAZON and normalized_asin:
        return f"https://amazon.com/dp/{normalized_asin}"
    if source == PurchaseFileImportSource.GOODWILL and normalized_item_id:
        return f"https://shopgoodwill.com/item/{normalized_item_id}"
    # Future eBay import mapping:
    # if source == PurchaseFileImportSource.EBAY and normalized_item_id:
    #     return f"https://www.ebay.com/itm/{normalized_item_id}"

    return None


def _map_zoho_po_status(status_raw: object) -> PurchaseDeliverStatus:
    status_text = str(status_raw or "").strip().lower()
    if status_text in {"billed", "partially_billed"}:
        return PurchaseDeliverStatus.BILLED
    if status_text in {"closed", "received"}:
        return PurchaseDeliverStatus.DELIVERED
    return PurchaseDeliverStatus.CREATED


def _extract_custom_field_decimal(po_payload: dict, *keys: str) -> Decimal:
    aliases = _build_custom_field_aliases(*keys)
    custom_hash = po_payload.get("custom_field_hash") or {}
    if isinstance(custom_hash, dict):
        for key, raw_value in custom_hash.items():
            normalized = _normalize_custom_field_key(key)
            if normalized.endswith("_unformatted"):
                normalized = normalized[: -len("_unformatted")]
            if normalized in aliases:
                return _to_decimal(raw_value, default="0")

    custom_fields = po_payload.get("custom_fields") or []
    if isinstance(custom_fields, list):
        for field in custom_fields:
            if not isinstance(field, dict):
                continue
            candidates = {
                _normalize_custom_field_key(field.get("api_name")),
                _normalize_custom_field_key(field.get("label")),
                _normalize_custom_field_key(field.get("field_name")),
            }
            if candidates.isdisjoint(aliases):
                continue
            if "value_unformatted" in field:
                return _to_decimal(field.get("value_unformatted"), default="0")
            if "value" in field:
                return _to_decimal(field.get("value"), default="0")
            if "value_formatted" in field:
                return _to_decimal(field.get("value_formatted"), default="0")

    return Decimal("0")


def _sum_line_item_tax_amounts(po_payload: dict) -> Decimal:
    tax_total = Decimal("0")
    line_items = po_payload.get("line_items") or []
    if not isinstance(line_items, list):
        return tax_total

    for line in line_items:
        if not isinstance(line, dict):
            continue
        for line_tax in line.get("line_item_taxes") or []:
            if not isinstance(line_tax, dict):
                continue
            tax_total += _to_decimal(line_tax.get("tax_amount"), default="0")
    return tax_total


def _extract_zoho_po_charges(po_payload: dict) -> tuple[Decimal, Decimal, Decimal]:
    # Sandbox/custom-field setup
    tax_amount = _extract_custom_field_decimal(po_payload, "cf_tax", "tax")
    shipping_amount = _extract_custom_field_decimal(po_payload, "cf_shipping_fee", "shipping_fee", "shipping")
    handling_amount = _extract_custom_field_decimal(po_payload, "cf_handling_fee", "handling_fee", "handling")

    # Standard totals fallback
    if tax_amount == 0:
        tax_amount = _to_decimal(po_payload.get("tax_total"), default="0")

    # Old-main fallback: tax can only be present per-line in line_item_taxes
    if tax_amount == 0:
        tax_amount = _sum_line_item_tax_amounts(po_payload)

    # Old-main fallback: shipping+handling packed into adjustment (S&H)
    adjustment_amount = _to_decimal(po_payload.get("adjustment"), default="0")
    if shipping_amount == 0 and handling_amount == 0 and adjustment_amount > 0:
        shipping_amount = adjustment_amount

    return tax_amount, shipping_amount, handling_amount


def _extract_zoho_po_tracking(po_payload: dict) -> str | None:
    for key in ("tracking_number", "reference_number", "shipment_tracking_number"):
        value = str(po_payload.get(key) or "").strip()
        if value:
            return value[:100]
    return None


@router.get("/vendors", response_model=list[VendorResponse])
async def list_vendors(
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    repo: VendorRepository = Depends(get_vendor_repo),
):
    vendors = await repo.get_multi(skip=skip, limit=limit, order_by="name")
    return [VendorResponse.model_validate(v) for v in vendors]


@router.post("/vendors", response_model=VendorResponse, status_code=status.HTTP_201_CREATED)
async def create_vendor(
    body: VendorCreate,
    repo: VendorRepository = Depends(get_vendor_repo),
    db: AsyncSession = Depends(get_db),
):
    existing = await repo.get_by_field("name", body.name)
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Vendor name already exists")

    vendor = await repo.create(body.model_dump())
    await db.commit()
    await db.refresh(vendor)
    return VendorResponse.model_validate(vendor)


@router.get("/vendors/{vendor_id}", response_model=VendorResponse)
async def get_vendor(vendor_id: int, repo: VendorRepository = Depends(get_vendor_repo)):
    vendor = await repo.get(vendor_id)
    if vendor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vendor not found")
    return VendorResponse.model_validate(vendor)


@router.patch("/vendors/{vendor_id}", response_model=VendorResponse)
async def update_vendor(
    vendor_id: int,
    body: VendorUpdate,
    repo: VendorRepository = Depends(get_vendor_repo),
    db: AsyncSession = Depends(get_db),
):
    vendor = await repo.get(vendor_id)
    if vendor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vendor not found")

    if body.name and body.name != vendor.name:
        existing = await repo.get_by_field("name", body.name)
        if existing is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Vendor name already exists")

    updated = await repo.update(vendor, body.model_dump(exclude_unset=True))
    await db.commit()
    await db.refresh(updated)
    return VendorResponse.model_validate(updated)


@router.get("/purchases", response_model=list[PurchaseOrderResponse])
async def list_purchase_orders(
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    order_date_from: Annotated[date | None, Query()] = None,
    order_date_to: Annotated[date | None, Query()] = None,
    deliver_status: Annotated[PurchaseDeliverStatus | None, Query()] = None,
    item_match_status: Annotated[str | None, Query(pattern="^(matched|unmatched)$")] = None,
    zoho_sync_status: Annotated[ZohoSyncStatus | None, Query()] = None,
    sort_by: Annotated[str, Query(pattern="^(order_date|po_number|total_amount|created_at)$")] = "order_date",
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "desc",
    repo: PurchaseOrderRepository = Depends(get_purchase_order_repo),
):
    rows = await repo.get_multi_with_date_filters(
        skip=skip,
        limit=limit,
        order_date_from=order_date_from,
        order_date_to=order_date_to,
        deliver_status=deliver_status,
        item_match_status=item_match_status,
        zoho_sync_status=zoho_sync_status,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )
    return [PurchaseOrderResponse.model_validate(r) for r in rows]


@router.post("/purchases", response_model=PurchaseOrderResponse, status_code=status.HTTP_201_CREATED)
async def create_purchase_order(
    body: PurchaseOrderCreate,
    po_repo: PurchaseOrderRepository = Depends(get_purchase_order_repo),
    po_item_repo: PurchaseOrderItemRepository = Depends(get_purchase_order_item_repo),
    vendor_repo: VendorRepository = Depends(get_vendor_repo),
    db: AsyncSession = Depends(get_db),
):
    vendor = await vendor_repo.get(body.vendor_id)
    if vendor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vendor not found")

    existing = await po_repo.get_by_field("po_number", body.po_number)
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="po_number already exists")

    po_payload = body.model_dump(exclude={"items"})
    po_payload["zoho_sync_status"] = ZohoSyncStatus.DIRTY
    po_payload["zoho_sync_error"] = None
    po = await po_repo.create(po_payload)

    for item in body.items:
        item_payload = item.model_dump()
        item_payload["purchase_order_id"] = po.id
        await po_item_repo.create(item_payload)

    await db.flush()
    fresh = await po_repo.get_with_items_and_vendor(po.id)
    await db.commit()
    if fresh is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to load PO")
    return PurchaseOrderResponse.model_validate(fresh)


@router.get("/purchases/{po_id}", response_model=PurchaseOrderResponse)
async def get_purchase_order(
    po_id: int,
    repo: PurchaseOrderRepository = Depends(get_purchase_order_repo),
):
    po = await repo.get_with_items_and_vendor(po_id)
    if po is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Purchase order not found")
    return PurchaseOrderResponse.model_validate(po)


@router.post(
    "/purchases/{po_id}/items",
    response_model=PurchaseOrderItemResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_purchase_order_item(
    po_id: int,
    body: PurchaseOrderItemCreate,
    po_repo: PurchaseOrderRepository = Depends(get_purchase_order_repo),
    po_item_repo: PurchaseOrderItemRepository = Depends(get_purchase_order_item_repo),
    db: AsyncSession = Depends(get_db),
):
    po = await po_repo.get(po_id)
    if po is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Purchase order not found")

    payload = body.model_dump()
    payload["purchase_order_id"] = po_id

    created = await po_item_repo.create(payload)
    po.zoho_sync_status = ZohoSyncStatus.DIRTY
    po.zoho_sync_error = None
    db.add(po)
    await db.commit()
    await db.refresh(created)
    return PurchaseOrderItemResponse.model_validate(created)


@router.post("/purchases/items/{item_id}/match", response_model=PurchaseOrderItemResponse)
async def match_purchase_order_item(
    item_id: int,
    body: PurchaseOrderItemMatchRequest,
    service: PurchasingService = Depends(get_purchasing_service),
    db: AsyncSession = Depends(get_db),
):
    try:
        item = await service.match_purchase_item(item_id=item_id, variant_id=body.variant_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    await db.commit()
    await db.refresh(item)
    return PurchaseOrderItemResponse.model_validate(item)


@router.patch("/purchases/items/{item_id}", response_model=PurchaseOrderItemResponse)
async def update_purchase_order_item(
    item_id: int,
    body: PurchaseOrderItemUpdate,
    po_item_repo: PurchaseOrderItemRepository = Depends(get_purchase_order_item_repo),
    db: AsyncSession = Depends(get_db),
):
    item = await po_item_repo.get(item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Purchase order item not found")

    if item.status == PurchaseOrderItemStatus.RECEIVED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Received items cannot be edited",
        )

    payload = body.model_dump(exclude_unset=True)

    if "variant_id" in payload:
        variant_id = payload.get("variant_id")
        if variant_id is not None:
            variant = await db.get(ProductVariant, variant_id)
            if variant is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"ProductVariant {variant_id} not found",
                )
            payload["status"] = PurchaseOrderItemStatus.MATCHED
        else:
            payload["status"] = PurchaseOrderItemStatus.UNMATCHED

    updated = await po_item_repo.update(item, payload)
    po = await db.get(PurchaseOrder, item.purchase_order_id)
    if po is not None:
        po.zoho_sync_status = ZohoSyncStatus.DIRTY
        po.zoho_sync_error = None
        db.add(po)
    await db.commit()
    await db.refresh(updated)
    return PurchaseOrderItemResponse.model_validate(updated)


@router.delete("/purchases/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_purchase_order_item(
    item_id: int,
    po_item_repo: PurchaseOrderItemRepository = Depends(get_purchase_order_item_repo),
    db: AsyncSession = Depends(get_db),
):
    item = await po_item_repo.get(item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Purchase order item not found")

    if item.status == PurchaseOrderItemStatus.RECEIVED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Received items cannot be deleted",
        )

    po = await db.get(PurchaseOrder, item.purchase_order_id)
    if po is not None:
        po.zoho_sync_status = ZohoSyncStatus.DIRTY
        po.zoho_sync_error = None
        db.add(po)

    await po_item_repo.delete(item_id)
    await db.commit()


@router.post("/purchases/{po_id}/mark-delivered", response_model=PurchaseOrderReceiveResponse)
async def mark_purchase_order_delivered(
    po_id: int,
    body: PurchaseOrderReceiveRequest,
    _current_user: AdminOrWarehouseUser,
    service: PurchasingService = Depends(get_purchasing_service),
    po_repo: PurchaseOrderRepository = Depends(get_purchase_order_repo),
    db: AsyncSession = Depends(get_db),
):
    try:
        created_rows = await service.receive_purchase_order(po_id, body.items)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    po = await po_repo.get(po_id)
    await db.commit()
    if po is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Purchase order not found")

    return PurchaseOrderReceiveResponse(
        purchase_order_id=po_id,
        created_inventory_item_ids=[row.id for row in created_rows],
        deliver_status=po.deliver_status,
    )


@router.post("/purchases/import/zoho", response_model=ZohoPurchaseImportResponse)
async def import_purchasing_from_zoho(
    _current_user: CurrentUser,
    max_pages: Annotated[int, Query(ge=1, le=50)] = 10,
    per_page: Annotated[int, Query(ge=1, le=200)] = 200,
    order_date_from: Annotated[date | None, Query()] = None,
    order_date_to: Annotated[date | None, Query()] = None,
    vendor_repo: VendorRepository = Depends(get_vendor_repo),
    po_repo: PurchaseOrderRepository = Depends(get_purchase_order_repo),
    po_item_repo: PurchaseOrderItemRepository = Depends(get_purchase_order_item_repo),
    db: AsyncSession = Depends(get_db),
):
    """Import vendors and purchase orders from Zoho into local purchasing tables."""
    if order_date_from is None or order_date_to is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="order_date_from and order_date_to are required",
        )

    if order_date_from and order_date_to and order_date_from > order_date_to:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="order_date_from must be less than or equal to order_date_to",
        )

    zoho = ZohoClient()
    variant_repo = ProductVariantRepository(db)
    result = ZohoPurchaseImportResponse()

    vendors_by_zoho_id: dict[str, int] = {}
    page = 1
    while page <= max_pages:
        contacts = await zoho.list_contacts(page=page, per_page=per_page)
        if not contacts:
            break

        vendor_contacts = [
            c for c in contacts if str(c.get("contact_type", "")).strip().lower() == "vendor"
        ]
        result.source_vendors_seen += len(vendor_contacts)

        for contact in vendor_contacts:
            zoho_id = str(contact.get("contact_id") or "").strip()
            name = str(contact.get("contact_name") or "").strip()
            if not zoho_id and not name:
                continue

            existing = await vendor_repo.get_by_field("zoho_id", zoho_id) if zoho_id else None
            if existing is None and name:
                existing = await vendor_repo.get_by_field("name", name)

            payload = {
                "name": name or f"Zoho Vendor {zoho_id}",
                "email": contact.get("email"),
                "phone": contact.get("phone") or contact.get("mobile"),
                "address": contact.get("billing_address") and str(contact.get("billing_address")),
                "is_active": True,
                "zoho_id": zoho_id or None,
            }

            if existing is None:
                created = await vendor_repo.create(payload)
                await db.flush()
                result.vendors_created += 1
                if created.zoho_id:
                    vendors_by_zoho_id[created.zoho_id] = created.id
            else:
                await vendor_repo.update(existing, payload)
                await db.flush()
                result.vendors_updated += 1
                if existing.zoho_id:
                    vendors_by_zoho_id[existing.zoho_id] = existing.id

        if len(contacts) < per_page:
            break
        page += 1

    page = 1
    while page <= max_pages:
        purchase_orders = await zoho.list_purchase_orders(page=page, per_page=per_page)
        if not purchase_orders:
            break

        result.source_purchase_orders_seen += len(purchase_orders)

        for zoho_po in purchase_orders:
            zoho_po_id = str(zoho_po.get("purchaseorder_id") or "").strip()
            po_number = str(zoho_po.get("purchaseorder_number") or "").strip()
            vendor_zoho_id = str(zoho_po.get("vendor_id") or "").strip()

            # Apply period filter early using list payload date to avoid importing out-of-range
            # orders and to skip unnecessary detail API calls.
            list_level_order_date = _to_date_or_none(
                zoho_po.get("date") or zoho_po.get("purchaseorder_date")
            )
            if order_date_from is not None:
                if list_level_order_date is None or list_level_order_date < order_date_from:
                    continue
            if order_date_to is not None:
                if list_level_order_date is None or list_level_order_date > order_date_to:
                    continue

            # Zoho list endpoint often omits line_items; fetch full PO details when possible.
            zoho_po_detail = zoho_po
            if zoho_po_id:
                try:
                    detail = await zoho.get_purchase_order(zoho_po_id)
                    if isinstance(detail, dict) and detail:
                        zoho_po_detail = detail
                except Exception:
                    # Keep import resilient; fall back to list payload if detail call fails.
                    zoho_po_detail = zoho_po

            if not po_number:
                continue

            vendor_id = vendors_by_zoho_id.get(vendor_zoho_id)
            if vendor_id is None and vendor_zoho_id:
                vendor_obj = await vendor_repo.get_by_field("zoho_id", vendor_zoho_id)
                if vendor_obj is not None:
                    vendor_id = vendor_obj.id
            if vendor_id is None:
                continue

            existing_po = await po_repo.get_by_field("zoho_id", zoho_po_id) if zoho_po_id else None
            if existing_po is None:
                existing_po = await po_repo.get_by_field("po_number", po_number)

            tax_amount, shipping_amount, handling_amount = _extract_zoho_po_charges(zoho_po_detail)
            order_date_value = _to_date_or_none(
                zoho_po_detail.get("date")
                or zoho_po_detail.get("purchaseorder_date")
                or zoho_po.get("date")
                or zoho_po.get("purchaseorder_date")
            )

            if order_date_value is None:
                continue
            if order_date_from is not None and order_date_value < order_date_from:
                continue
            if order_date_to is not None and order_date_value > order_date_to:
                continue

            po_payload = {
                "po_number": po_number,
                "vendor_id": vendor_id,
                "deliver_status": _map_zoho_po_status(
                    zoho_po_detail.get("status")
                    or zoho_po_detail.get("purchaseorder_status")
                    or zoho_po.get("status")
                    or zoho_po.get("purchaseorder_status")
                ),
                "order_date": order_date_value,
                "expected_delivery_date": _to_date(zoho_po_detail.get("expected_delivery_date"))
                if zoho_po_detail.get("expected_delivery_date")
                else None,
                "total_amount": _to_decimal(
                    zoho_po_detail.get("total")
                    or zoho_po_detail.get("total_amount")
                    or zoho_po.get("total")
                    or zoho_po.get("total_amount")
                    or 0
                ),
                "currency": str(
                    zoho_po_detail.get("currency_code")
                    or zoho_po.get("currency_code")
                    or "USD"
                )[:3],
                "tracking_number": _extract_zoho_po_tracking(zoho_po_detail) or _extract_zoho_po_tracking(zoho_po),
                "tax_amount": tax_amount,
                "shipping_amount": shipping_amount,
                "handling_amount": handling_amount,
                "source": "ZOHO_IMPORT",
                "notes": zoho_po_detail.get("notes") or zoho_po_detail.get("terms") or zoho_po.get("notes") or zoho_po.get("terms"),
                "zoho_id": zoho_po_id or None,
                "zoho_sync_status": ZohoSyncStatus.SYNCED,
                "zoho_sync_error": None,
                "zoho_last_synced_at": datetime.utcnow(),
            }

            if existing_po is None:
                local_po = await po_repo.create(po_payload)
                await db.flush()
                result.purchase_orders_created += 1
            else:
                local_po = await po_repo.update(existing_po, po_payload)
                await db.flush()
                result.purchase_orders_updated += 1

            existing_item_names_by_external_id: dict[str, str] = {}
            existing_item_names_by_position: list[str] = []
            existing_items = await db.execute(
                select(
                    PurchaseOrderItem.external_item_id,
                    PurchaseOrderItem.external_item_name,
                )
                .where(PurchaseOrderItem.purchase_order_id == local_po.id)
                .order_by(PurchaseOrderItem.id.asc())
            )
            for existing_external_item_id, existing_external_item_name in existing_items.all():
                normalized_existing_name = str(existing_external_item_name or "").strip()
                if normalized_existing_name:
                    existing_item_names_by_position.append(normalized_existing_name)
                    if existing_external_item_id:
                        existing_item_names_by_external_id[existing_external_item_id] = normalized_existing_name

            # Replace all local line-items with Zoho line-items for deterministic import.
            await db.execute(
                delete(PurchaseOrderItem).where(PurchaseOrderItem.purchase_order_id == local_po.id)
            )

            line_items = zoho_po_detail.get("line_items", []) or zoho_po.get("line_items", []) or []
            for line_index, line in enumerate(line_items):
                qty = int(line.get("quantity") or 0)
                unit_price = _to_decimal(line.get("rate") or line.get("item_total") or 0)
                total_price = _to_decimal(line.get("item_total") or (unit_price * qty))
                if qty <= 0:
                    continue

                # Zoho may provide different SKU keys depending on payload shape.
                line_sku = str(
                    line.get("sku")
                    or line.get("item_sku")
                    or line.get("product_sku")
                    or ""
                ).strip()
                matched_variant = None
                if line_sku:
                    matched_variant = await variant_repo.get_by_sku(line_sku.upper())
                    if matched_variant is not None and not matched_variant.is_active:
                        matched_variant = None
                if matched_variant is None:
                    zoho_item_id = str(line.get("item_id") or "").strip()
                    if zoho_item_id:
                        matched_variant = await variant_repo.get_by_zoho_id(zoho_item_id)
                        if matched_variant is not None and not matched_variant.is_active:
                            matched_variant = None

                external_item_id = (
                    str(line.get("line_item_id") or line.get("item_id") or line_sku or "").strip() or None
                )
                preserved_item_name = (
                    existing_item_names_by_external_id.get(external_item_id)
                    if external_item_id is not None
                    else None
                )
                if preserved_item_name is None and line_index < len(existing_item_names_by_position):
                    preserved_item_name = existing_item_names_by_position[line_index]

                await po_item_repo.create(
                    {
                        "purchase_order_id": local_po.id,
                        "variant_id": matched_variant.id if matched_variant else None,
                        "external_item_id": external_item_id,
                        "external_item_name": _resolve_zoho_external_item_name(
                            existing_name=preserved_item_name,
                        ),
                        "quantity": qty,
                        "unit_price": unit_price,
                        "total_price": total_price,
                        "status": (
                            PurchaseOrderItemStatus.MATCHED
                            if matched_variant
                            else PurchaseOrderItemStatus.UNMATCHED
                        ),
                    }
                )
                result.purchase_order_items_replaced += 1

        if len(purchase_orders) < per_page:
            break
        page += 1

    await db.commit()
    return result


async def _resolve_vendor_id(
    vendor_name: str,
    vendor_repo: VendorRepository,
    db: AsyncSession,
    vendor_cache: dict[str, int],
) -> int:
    normalized_name = vendor_name.strip() or "Unknown Vendor"
    cache_key = normalized_name.lower()
    if cache_key in vendor_cache:
        return vendor_cache[cache_key]

    existing = await vendor_repo.get_by_field("name", normalized_name)
    if existing is None:
        existing = await vendor_repo.create({"name": normalized_name, "is_active": True})
        await db.flush()

    vendor_cache[cache_key] = existing.id
    return existing.id


async def _upsert_purchase_item(
    local_po_id: int,
    item_id: str | None,
    purchase_item_link: str | None,
    item_name: str,
    quantity: int,
    unit_price: Decimal,
    po_item_repo: PurchaseOrderItemRepository,
    db: AsyncSession,
    result: PurchaseFileImportResponse,
):
    local_po = await db.get(PurchaseOrder, local_po_id)
    if local_po is not None:
        local_po.zoho_sync_status = ZohoSyncStatus.DIRTY
        local_po.zoho_sync_error = None
        db.add(local_po)

    existing_item = None
    if item_id:
        stmt = select(PurchaseOrderItem).where(
            PurchaseOrderItem.purchase_order_id == local_po_id,
            PurchaseOrderItem.external_item_id == item_id,
        )
        existing_item = (await db.execute(stmt)).scalar_one_or_none()

    line_total = unit_price * quantity
    normalized_purchase_item_link = (purchase_item_link or "").strip() or None
    if normalized_purchase_item_link:
        normalized_purchase_item_link = normalized_purchase_item_link[:500]

    if existing_item is None and normalized_purchase_item_link:
        stmt = select(PurchaseOrderItem).where(
            PurchaseOrderItem.purchase_order_id == local_po_id,
            PurchaseOrderItem.purchase_item_link == normalized_purchase_item_link,
        )
        existing_item = (await db.execute(stmt)).scalar_one_or_none()

    if existing_item is None:
        stmt = select(PurchaseOrderItem).where(
            PurchaseOrderItem.purchase_order_id == local_po_id,
            PurchaseOrderItem.external_item_name == item_name,
        )
        existing_item = (await db.execute(stmt)).scalar_one_or_none()

    item_payload = {
        "purchase_order_id": local_po_id,
        "external_item_id": item_id,
        "purchase_item_link": normalized_purchase_item_link,
        "external_item_name": item_name[:255],
        "quantity": quantity,
        "unit_price": unit_price,
        "total_price": line_total,
    }

    if existing_item is None:
        item_payload["variant_id"] = None
        item_payload["status"] = PurchaseOrderItemStatus.UNMATCHED
        await po_item_repo.create(item_payload)
        result.purchase_order_items_created += 1
    else:
        # Preserve prior matching state and variant linkage on re-import.
        item_payload["variant_id"] = existing_item.variant_id
        item_payload["status"] = existing_item.status
        await po_item_repo.update(existing_item, item_payload)
        result.purchase_order_items_updated += 1


async def _import_goodwill_csv(
    content: str,
    vendor_repo: VendorRepository,
    po_repo: PurchaseOrderRepository,
    po_item_repo: PurchaseOrderItemRepository,
    db: AsyncSession,
) -> PurchaseFileImportResponse:
    reader = csv.DictReader(io.StringIO(content))
    if not reader.fieldnames:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CSV header row is missing")

    required_headers = [
        "Order #",
        "Item Id",
        "Item",
        "Quantity",
        "Price",
        "Date",
        "Tracking #",
        "Tax",
        "Shipping",
        "Handling",
    ]
    missing_headers = [h for h in required_headers if h not in reader.fieldnames]
    if missing_headers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"CSV is missing required columns: {', '.join(missing_headers)}",
        )

    result = PurchaseFileImportResponse(source=PurchaseFileImportSource.GOODWILL)
    vendor_cache: dict[str, int] = {}
    goodwill_vendor_id = await _resolve_vendor_id("Goodwill", vendor_repo, db, vendor_cache)

    for row in reader:
        result.source_rows_seen += 1

        po_number = str(row.get("Order #") or "").strip()
        item_id = str(row.get("Item Id") or "").strip() or None
        purchase_item_link = _build_purchase_item_link(
            PurchaseFileImportSource.GOODWILL,
            item_id=item_id,
        )
        item_name = str(row.get("Item") or "").strip()
        if not po_number or not item_name:
            result.source_rows_skipped += 1
            continue

        quantity = _to_int(row.get("Quantity"), default=0)
        if quantity <= 0:
            result.source_rows_skipped += 1
            continue

        unit_price = _to_decimal(row.get("Price"), default="0")
        tax_amount = _to_decimal(row.get("Tax"), default="0")
        shipping_amount = _to_decimal(row.get("Shipping"), default="0")
        handling_amount = _to_decimal(row.get("Handling"), default="0")
        order_date = _to_date(row.get("Date"))
        tracking_number = str(row.get("Tracking #") or "").strip() or None
        total_amount = (unit_price * quantity) + tax_amount + shipping_amount + handling_amount

        existing_po = await po_repo.get_by_field("po_number", po_number)
        po_payload = {
            "po_number": po_number,
            "vendor_id": goodwill_vendor_id,
            "deliver_status": PurchaseDeliverStatus.CREATED,
            "order_date": order_date,
            "expected_delivery_date": None,
            "total_amount": total_amount,
            "currency": "USD",
            "tracking_number": tracking_number,
            "tax_amount": tax_amount,
            "shipping_amount": shipping_amount,
            "handling_amount": handling_amount,
            "source": "GOODWILL_CSV",
            "notes": "Imported from Goodwill shipped-orders CSV.",
            "zoho_sync_status": ZohoSyncStatus.DIRTY,
            "zoho_sync_error": None,
        }

        if existing_po is None:
            local_po = await po_repo.create(po_payload)
            await db.flush()
            result.purchase_orders_created += 1
        else:
            local_po = await po_repo.update(existing_po, po_payload)
            await db.flush()
            result.purchase_orders_updated += 1

        await _upsert_purchase_item(
            local_po_id=local_po.id,
            item_id=item_id,
            purchase_item_link=purchase_item_link,
            item_name=item_name,
            quantity=quantity,
            unit_price=unit_price,
            po_item_repo=po_item_repo,
            db=db,
            result=result,
        )

    return result


async def _import_amazon_csv(
    content: str,
    vendor_repo: VendorRepository,
    po_repo: PurchaseOrderRepository,
    po_item_repo: PurchaseOrderItemRepository,
    db: AsyncSession,
) -> PurchaseFileImportResponse:
    reader = csv.DictReader(io.StringIO(content))
    if not reader.fieldnames:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CSV header row is missing")

    required_headers = ["Order ID", "Order Date", "Title", "Item Quantity"]
    missing_headers = [h for h in required_headers if h not in reader.fieldnames]
    if missing_headers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"CSV is missing required columns: {', '.join(missing_headers)}",
        )

    result = PurchaseFileImportResponse(source=PurchaseFileImportSource.AMAZON)
    vendor_cache: dict[str, int] = {}
    grouped_orders: dict[str, dict] = {}
    excluded_account_user = "dragonhn"

    for row in reader:
        result.source_rows_seen += 1

        account_user = str(row.get("Account User") or "").strip().lower()
        if account_user == excluded_account_user:
            result.source_rows_skipped += 1
            continue

        po_number = str(row.get("Order ID") or "").strip()
        item_name = str(row.get("Title") or "").strip()
        quantity = _to_int(row.get("Item Quantity"), default=0)
        if not po_number or not item_name or quantity <= 0:
            result.source_rows_skipped += 1
            continue

        vendor_name = str(row.get("Seller Name") or "").strip() or "Amazon Marketplace"
        currency = _normalize_currency(row.get("Currency") or "USD")
        item_unit_price = _to_decimal(row.get("Purchase PPU"), default="0")
        if item_unit_price <= 0:
            subtotal_guess = _to_decimal(row.get("Item Subtotal"), default="0")
            if subtotal_guess > 0 and quantity > 0:
                item_unit_price = subtotal_guess / quantity
        item_total = _to_decimal(row.get("Item Net Total") or row.get("Item Subtotal"), default="0")
        if item_total <= 0:
            item_total = item_unit_price * quantity

        order_bucket = grouped_orders.setdefault(
            po_number,
            {
                "vendor_name": vendor_name,
                "order_date": _to_date(row.get("Order Date")),
                "currency": currency,
                "tracking_number": None,
                "tax_amount": _to_decimal(row.get("Order Tax"), default="0"),
                "shipping_amount": _to_decimal(row.get("Order Shipping & Handling"), default="0"),
                "handling_amount": Decimal("0"),
                "total_amount": _to_decimal(row.get("Order Net Total"), default="0"),
                "items": [],
                "fingerprints": set(),
            },
        )

        asin = str(row.get("ASIN") or "").strip()
        line_item_id = str(row.get("PO Line Item Id") or "").strip()
        external_item_id = line_item_id or asin or None
        purchase_item_link = _build_purchase_item_link(
            PurchaseFileImportSource.AMAZON,
            asin=asin,
        )
        fingerprint = (
            external_item_id or "",
            purchase_item_link or "",
            item_name,
            str(quantity),
            str(item_unit_price),
            str(item_total),
        )
        if fingerprint in order_bucket["fingerprints"]:
            continue
        order_bucket["fingerprints"].add(fingerprint)
        order_bucket["items"].append(
            {
                "external_item_id": external_item_id,
                "purchase_item_link": purchase_item_link,
                "external_item_name": item_name,
                "quantity": quantity,
                "unit_price": item_unit_price,
            }
        )

    for po_number, order_data in grouped_orders.items():
        if not order_data["items"]:
            result.source_rows_skipped += 1
            continue

        vendor_id = await _resolve_vendor_id(order_data["vendor_name"], vendor_repo, db, vendor_cache)
        computed_total = sum(
            (item["unit_price"] * item["quantity"] for item in order_data["items"]),
            Decimal("0"),
        ) + order_data["tax_amount"] + order_data["shipping_amount"] + order_data["handling_amount"]
        total_amount = order_data["total_amount"] if order_data["total_amount"] > 0 else computed_total

        existing_po = await po_repo.get_by_field("po_number", po_number)
        po_payload = {
            "po_number": po_number,
            "vendor_id": vendor_id,
            "deliver_status": PurchaseDeliverStatus.CREATED,
            "order_date": order_data["order_date"],
            "expected_delivery_date": None,
            "total_amount": total_amount,
            "currency": order_data["currency"],
            "tracking_number": order_data["tracking_number"],
            "tax_amount": order_data["tax_amount"],
            "shipping_amount": order_data["shipping_amount"],
            "handling_amount": order_data["handling_amount"],
            "source": "AMAZON_CSV",
            "notes": "Imported from Amazon orders CSV.",
            "zoho_sync_status": ZohoSyncStatus.DIRTY,
            "zoho_sync_error": None,
        }

        if existing_po is None:
            local_po = await po_repo.create(po_payload)
            await db.flush()
            result.purchase_orders_created += 1
        else:
            local_po = await po_repo.update(existing_po, po_payload)
            await db.flush()
            result.purchase_orders_updated += 1

        for item in order_data["items"]:
            await _upsert_purchase_item(
                local_po_id=local_po.id,
                item_id=item["external_item_id"],
                purchase_item_link=item.get("purchase_item_link"),
                item_name=item["external_item_name"],
                quantity=item["quantity"],
                unit_price=item["unit_price"],
                po_item_repo=po_item_repo,
                db=db,
                result=result,
            )

    return result


async def _import_aliexpress_json(
    content: str,
    vendor_repo: VendorRepository,
    po_repo: PurchaseOrderRepository,
    po_item_repo: PurchaseOrderItemRepository,
    db: AsyncSession,
) -> PurchaseFileImportResponse:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid JSON: {exc.msg}")

    if not isinstance(payload, list):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="AliExpress JSON must be an array of orders")

    result = PurchaseFileImportResponse(source=PurchaseFileImportSource.ALIEXPRESS)
    vendor_cache: dict[str, int] = {}

    for order in payload:
        result.source_rows_seen += 1
        if not isinstance(order, dict):
            result.source_rows_skipped += 1
            continue

        po_number = str(order.get("orderId") or "").strip()
        items = order.get("items") or []
        if not po_number or not isinstance(items, list) or not items:
            result.source_rows_skipped += 1
            continue

        seller = order.get("seller") or {}
        seller_name = str((seller or {}).get("storeName") or "").strip() or "AliExpress Seller"
        vendor_id = await _resolve_vendor_id(seller_name, vendor_repo, db, vendor_cache)

        price_data = order.get("priceData") or {}
        tax_amount = _to_decimal(price_data.get("vat"), default="0")
        shipping_amount = _to_decimal(price_data.get("shipping"), default="0")
        handling_amount = _to_decimal(price_data.get("priceAdjustment"), default="0")
        if handling_amount < 0:
            handling_amount = Decimal("0")

        parsed_items: list[dict] = []
        order_detail_link = str(order.get("orderDetailLink") or "").strip() or None
        for item in items:
            if not isinstance(item, dict):
                continue
            quantity = _to_int(item.get("quantity"), default=0)
            if quantity <= 0:
                continue
            unit_price = _to_decimal(item.get("priceAmount"), default="0")
            item_title = str(item.get("title") or "").strip()
            item_attributes = str(item.get("attributes") or "").strip()
            if not item_title:
                continue
            external_item_name = item_title if not item_attributes else f"{item_title} ({item_attributes})"
            external_item_id = str(item.get("itemId") or item.get("productId") or item.get("skuId") or "").strip() or None
            product_link = str(item.get("productLink") or "").strip() or order_detail_link
            parsed_items.append(
                {
                    "external_item_id": external_item_id,
                    "purchase_item_link": product_link,
                    "external_item_name": external_item_name,
                    "quantity": quantity,
                    "unit_price": unit_price,
                }
            )

        if not parsed_items:
            result.source_rows_skipped += 1
            continue

        items_total = sum((item["unit_price"] * item["quantity"] for item in parsed_items), Decimal("0"))
        total_amount = _to_decimal(price_data.get("total"), default="0")
        if total_amount <= 0:
            total_amount = items_total + tax_amount + shipping_amount + handling_amount

        tracking_data = order.get("trackingData") or {}
        tracking_number = str((tracking_data or {}).get("trackingNumber") or "").strip() or None
        order_date = _to_date(order.get("orderDate") or order.get("orderDateTimestampFormat"))

        existing_po = await po_repo.get_by_field("po_number", po_number)
        po_payload = {
            "po_number": po_number,
            "vendor_id": vendor_id,
            "deliver_status": PurchaseDeliverStatus.CREATED,
            "order_date": order_date,
            "expected_delivery_date": None,
            "total_amount": total_amount,
            "currency": _normalize_currency(order.get("currency") or "USD"),
            "tracking_number": tracking_number,
            "tax_amount": tax_amount,
            "shipping_amount": shipping_amount,
            "handling_amount": handling_amount,
            "source": "ALIEXPRESS_JSON",
            "notes": "Imported from AliExpress orders JSON.",
            "zoho_sync_status": ZohoSyncStatus.DIRTY,
            "zoho_sync_error": None,
        }

        if existing_po is None:
            local_po = await po_repo.create(po_payload)
            await db.flush()
            result.purchase_orders_created += 1
        else:
            local_po = await po_repo.update(existing_po, po_payload)
            await db.flush()
            result.purchase_orders_updated += 1

        for item in parsed_items:
            await _upsert_purchase_item(
                local_po_id=local_po.id,
                item_id=item["external_item_id"],
                purchase_item_link=item.get("purchase_item_link"),
                item_name=item["external_item_name"],
                quantity=item["quantity"],
                unit_price=item["unit_price"],
                po_item_repo=po_item_repo,
                db=db,
                result=result,
            )

    return result


async def _import_purchase_file_by_source(
    source: PurchaseFileImportSource,
    file: UploadFile,
    vendor_repo: VendorRepository,
    po_repo: PurchaseOrderRepository,
    po_item_repo: PurchaseOrderItemRepository,
    db: AsyncSession,
) -> PurchaseFileImportResponse:
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty")

    content = _decode_upload_text(raw)

    if source == PurchaseFileImportSource.GOODWILL:
        return await _import_goodwill_csv(content, vendor_repo, po_repo, po_item_repo, db)
    if source == PurchaseFileImportSource.AMAZON:
        return await _import_amazon_csv(content, vendor_repo, po_repo, po_item_repo, db)
    if source == PurchaseFileImportSource.ALIEXPRESS:
        return await _import_aliexpress_json(content, vendor_repo, po_repo, po_item_repo, db)

    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported import source")


@router.post("/purchases/import/file", response_model=PurchaseFileImportResponse)
async def import_purchasing_from_file(
    _current_user: CurrentUser,
    source: PurchaseFileImportSource = Query(...),
    file: UploadFile = File(...),
    vendor_repo: VendorRepository = Depends(get_vendor_repo),
    po_repo: PurchaseOrderRepository = Depends(get_purchase_order_repo),
    po_item_repo: PurchaseOrderItemRepository = Depends(get_purchase_order_item_repo),
    db: AsyncSession = Depends(get_db),
):
    result = await _import_purchase_file_by_source(
        source=source,
        file=file,
        vendor_repo=vendor_repo,
        po_repo=po_repo,
        po_item_repo=po_item_repo,
        db=db,
    )
    await db.commit()
    await file.close()
    return result


@router.post("/purchases/import/goodwill-csv", response_model=GoodwillCsvImportResponse)
async def import_purchasing_from_goodwill_csv(
    _current_user: CurrentUser,
    file: UploadFile = File(...),
    vendor_repo: VendorRepository = Depends(get_vendor_repo),
    po_repo: PurchaseOrderRepository = Depends(get_purchase_order_repo),
    po_item_repo: PurchaseOrderItemRepository = Depends(get_purchase_order_item_repo),
    db: AsyncSession = Depends(get_db),
):
    """Legacy endpoint kept for compatibility; delegates to source-based importer."""
    result = await _import_purchase_file_by_source(
        source=PurchaseFileImportSource.GOODWILL,
        file=file,
        vendor_repo=vendor_repo,
        po_repo=po_repo,
        po_item_repo=po_item_repo,
        db=db,
    )
    await db.commit()
    await file.close()
    return GoodwillCsvImportResponse(
        purchase_orders_created=result.purchase_orders_created,
        purchase_orders_updated=result.purchase_orders_updated,
        purchase_order_items_created=result.purchase_order_items_created,
        purchase_order_items_updated=result.purchase_order_items_updated,
        source_rows_seen=result.source_rows_seen,
        source_rows_skipped=result.source_rows_skipped,
    )
