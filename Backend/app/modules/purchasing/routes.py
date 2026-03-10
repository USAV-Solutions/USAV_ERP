"""API routes for purchasing module."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminOrWarehouseUser
from app.core.database import get_db
from app.modules.purchasing.dependencies import (
    get_purchase_order_item_repo,
    get_purchase_order_repo,
    get_purchasing_service,
    get_vendor_repo,
)
from app.modules.purchasing.schemas import (
    PurchaseOrderCreate,
    PurchaseOrderItemMatchRequest,
    PurchaseOrderItemResponse,
    PurchaseOrderReceiveRequest,
    PurchaseOrderReceiveResponse,
    PurchaseOrderResponse,
    VendorCreate,
    VendorResponse,
    VendorUpdate,
)
from app.modules.purchasing.service import PurchasingService
from app.repositories.purchasing import (
    PurchaseOrderItemRepository,
    PurchaseOrderRepository,
    VendorRepository,
)

router = APIRouter(tags=["Purchasing"])


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
