"""API routes for purchasing module."""
import csv
import io
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminOrWarehouseUser, CurrentUser
from app.core.database import get_db
from app.integrations.zoho.client import ZohoClient
from app.models import PurchaseDeliverStatus, PurchaseOrderItemStatus
from app.models.entities import ProductVariant
from app.models.purchasing import PurchaseOrderItem
from app.modules.purchasing.dependencies import (
    get_purchase_order_item_repo,
    get_purchase_order_repo,
    get_purchasing_service,
    get_vendor_repo,
)
from app.modules.purchasing.schemas import (
    GoodwillCsvImportResponse,
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
            for fmt in ("%m/%d/%Y", "%m/%d/%y"):
                try:
                    return datetime.strptime(text, fmt).date()
                except ValueError:
                    continue
    return date.today()


def _to_int(value: object, default: int = 0) -> int:
    try:
        text = str(value if value is not None else default).replace(",", "").strip()
        if text == "":
            return default
        return int(Decimal(text))
    except Exception:
        return default


def _map_zoho_po_status(status_raw: object) -> PurchaseDeliverStatus:
    status_text = str(status_raw or "").strip().lower()
    if status_text in {"billed", "partially_billed"}:
        return PurchaseDeliverStatus.BILLED
    if status_text in {"closed", "received"}:
        return PurchaseDeliverStatus.DELIVERED
    return PurchaseDeliverStatus.CREATED


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
    repo: PurchaseOrderRepository = Depends(get_purchase_order_repo),
):
    rows = await repo.get_multi(skip=skip, limit=limit, order_by="created_at")
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
    vendor_repo: VendorRepository = Depends(get_vendor_repo),
    po_repo: PurchaseOrderRepository = Depends(get_purchase_order_repo),
    po_item_repo: PurchaseOrderItemRepository = Depends(get_purchase_order_item_repo),
    db: AsyncSession = Depends(get_db),
):
    """Import vendors and purchase orders from Zoho into local purchasing tables."""
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

            po_payload = {
                "po_number": po_number,
                "vendor_id": vendor_id,
                "deliver_status": _map_zoho_po_status(
                    zoho_po_detail.get("status")
                    or zoho_po_detail.get("purchaseorder_status")
                    or zoho_po.get("status")
                    or zoho_po.get("purchaseorder_status")
                ),
                "order_date": _to_date(
                    zoho_po_detail.get("date")
                    or zoho_po_detail.get("purchaseorder_date")
                    or zoho_po.get("date")
                    or zoho_po.get("purchaseorder_date")
                ),
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
                "notes": zoho_po_detail.get("notes") or zoho_po_detail.get("terms") or zoho_po.get("notes") or zoho_po.get("terms"),
                "zoho_id": zoho_po_id or None,
            }

            if existing_po is None:
                local_po = await po_repo.create(po_payload)
                await db.flush()
                result.purchase_orders_created += 1
            else:
                local_po = await po_repo.update(existing_po, po_payload)
                await db.flush()
                result.purchase_orders_updated += 1

            # Replace all local line-items with Zoho line-items for deterministic import.
            await db.execute(
                delete(PurchaseOrderItem).where(PurchaseOrderItem.purchase_order_id == local_po.id)
            )

            line_items = zoho_po_detail.get("line_items", []) or zoho_po.get("line_items", []) or []
            for line in line_items:
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
                if matched_variant is None:
                    zoho_item_id = str(line.get("item_id") or "").strip()
                    if zoho_item_id:
                        matched_variant = await variant_repo.get_by_zoho_id(zoho_item_id)

                await po_item_repo.create(
                    {
                        "purchase_order_id": local_po.id,
                        "variant_id": matched_variant.id if matched_variant else None,
                        "external_item_name": str(line.get("name") or line.get("item_name") or "Unknown item")[:255],
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


@router.post("/purchases/import/goodwill-csv", response_model=GoodwillCsvImportResponse)
async def import_purchasing_from_goodwill_csv(
    _current_user: CurrentUser,
    file: UploadFile = File(...),
    vendor_repo: VendorRepository = Depends(get_vendor_repo),
    po_repo: PurchaseOrderRepository = Depends(get_purchase_order_repo),
    po_item_repo: PurchaseOrderItemRepository = Depends(get_purchase_order_item_repo),
    db: AsyncSession = Depends(get_db),
):
    """Import Goodwill shipped-orders CSV rows into local purchasing tables."""
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded CSV file is empty")

    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        content = raw.decode("latin-1")

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

    goodwill_vendor = await vendor_repo.get_by_field("name", "Goodwill")
    if goodwill_vendor is None:
        goodwill_vendor = await vendor_repo.create(
            {
                "name": "Goodwill",
                "is_active": True,
            }
        )
        await db.flush()

    result = GoodwillCsvImportResponse()

    for row in reader:
        result.source_rows_seen += 1

        po_number = str(row.get("Order #") or "").strip()
        item_id = str(row.get("Item Id") or "").strip() or None
        item_name = str(row.get("Item") or "").strip()
        if not po_number or not item_name:
            result.source_rows_skipped += 1
            continue

        quantity = _to_int(row.get("Quantity"), default=0)
        unit_price = _to_decimal(row.get("Price"), default="0")
        tax_amount = _to_decimal(row.get("Tax"), default="0")
        shipping_amount = _to_decimal(row.get("Shipping"), default="0")
        handling_amount = _to_decimal(row.get("Handling"), default="0")

        if quantity <= 0:
            result.source_rows_skipped += 1
            continue

        order_date = _to_date(row.get("Date"))
        tracking_number = str(row.get("Tracking #") or "").strip() or None
        total_amount = (unit_price * quantity) + tax_amount + shipping_amount + handling_amount

        existing_po = await po_repo.get_by_field("po_number", po_number)
        po_payload = {
            "po_number": po_number,
            "vendor_id": goodwill_vendor.id,
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
        }

        if existing_po is None:
            local_po = await po_repo.create(po_payload)
            await db.flush()
            result.purchase_orders_created += 1
        else:
            local_po = await po_repo.update(existing_po, po_payload)
            await db.flush()
            result.purchase_orders_updated += 1

        existing_item = None
        if item_id:
            stmt = select(PurchaseOrderItem).where(
                PurchaseOrderItem.purchase_order_id == local_po.id,
                PurchaseOrderItem.external_item_id == item_id,
            )
            existing_item = (await db.execute(stmt)).scalar_one_or_none()

        if existing_item is None:
            stmt = select(PurchaseOrderItem).where(
                PurchaseOrderItem.purchase_order_id == local_po.id,
                PurchaseOrderItem.external_item_name == item_name,
            )
            existing_item = (await db.execute(stmt)).scalar_one_or_none()

        line_total = unit_price * quantity
        item_payload = {
            "purchase_order_id": local_po.id,
            "variant_id": None,
            "external_item_id": item_id,
            "external_item_name": item_name,
            "quantity": quantity,
            "unit_price": unit_price,
            "total_price": line_total,
            "status": PurchaseOrderItemStatus.UNMATCHED,
        }

        if existing_item is None:
            await po_item_repo.create(item_payload)
            result.purchase_order_items_created += 1
        else:
            await po_item_repo.update(existing_item, item_payload)
            result.purchase_order_items_updated += 1

    await db.commit()
    await file.close()
    return result
