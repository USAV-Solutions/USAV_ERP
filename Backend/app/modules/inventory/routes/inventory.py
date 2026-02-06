"""
Inventory API endpoints.
Handles InventoryItem CRUD and status management.
"""
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models import InventoryStatus, InventoryItem, ProductVariant
from app.repositories import InventoryItemRepository, ProductVariantRepository
from app.modules.inventory.schemas import (
    InventoryItemCreate,
    InventoryItemResponse,
    InventoryItemUpdate,
    InventoryItemWithVariant,
    InventorySummary,
    InventoryReceiveRequest,
    InventoryReceiveResponse,
    InventoryMoveRequest,
    InventoryMoveResponse,
    InventoryAuditItem,
    InventoryAuditResponse,
    PaginatedResponse,
)

router = APIRouter(prefix="/inventory", tags=["Inventory"])


@router.get("", response_model=PaginatedResponse)
async def list_inventory(
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    variant_id: Annotated[int | None, Query(description="Filter by variant")] = None,
    status_filter: Annotated[InventoryStatus | None, Query(alias="status", description="Filter by status")] = None,
    location_code: Annotated[str | None, Query(description="Filter by location")] = None,
    db: AsyncSession = Depends(get_db),
):
    """List inventory items with optional filtering."""
    repo = InventoryItemRepository(db)
    
    filters = {}
    if variant_id is not None:
        filters["variant_id"] = variant_id
    if status_filter is not None:
        filters["status"] = status_filter
    if location_code is not None:
        filters["location_code"] = location_code
    
    items = await repo.get_multi(skip=skip, limit=limit, filters=filters, order_by="id")
    total = await repo.count(filters=filters)
    
    return PaginatedResponse(
        total=total,
        skip=skip,
        limit=limit,
        items=[InventoryItemResponse.model_validate(item) for item in items]
    )


@router.post("", response_model=InventoryItemResponse, status_code=status.HTTP_201_CREATED)
async def create_inventory_item(
    data: InventoryItemCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new inventory item."""
    inventory_repo = InventoryItemRepository(db)
    variant_repo = ProductVariantRepository(db)
    
    # Verify variant exists
    variant = await variant_repo.get(data.variant_id)
    if not variant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product variant {data.variant_id} not found"
        )
    
    # Check for duplicate serial number
    if data.serial_number:
        existing = await inventory_repo.get_by_serial(data.serial_number)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Inventory item with serial '{data.serial_number}' already exists"
            )
    
    item = await inventory_repo.create(data.model_dump())
    return InventoryItemResponse.model_validate(item)


@router.get("/{item_id}", response_model=InventoryItemWithVariant)
async def get_inventory_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get an inventory item by ID."""
    repo = InventoryItemRepository(db)
    item = await repo.get(item_id)
    
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Inventory item {item_id} not found"
        )
    
    return InventoryItemWithVariant.model_validate(item)


@router.get("/serial/{serial_number}", response_model=InventoryItemResponse)
async def get_inventory_by_serial(
    serial_number: str,
    db: AsyncSession = Depends(get_db),
):
    """Get an inventory item by serial number."""
    repo = InventoryItemRepository(db)
    item = await repo.get_by_serial(serial_number)
    
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Inventory item with serial '{serial_number}' not found"
        )
    
    return InventoryItemResponse.model_validate(item)


@router.put("/{item_id}", response_model=InventoryItemResponse)
@router.patch("/{item_id}", response_model=InventoryItemResponse)
async def update_inventory_item(
    item_id: int,
    data: InventoryItemUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update an inventory item (supports both PUT and PATCH)."""
    repo = InventoryItemRepository(db)
    item = await repo.get(item_id)
    
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Inventory item {item_id} not found"
        )
    
    # Check for duplicate serial if changing it
    if data.serial_number and data.serial_number != item.serial_number:
        existing = await repo.get_by_serial(data.serial_number)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Inventory item with serial '{data.serial_number}' already exists"
            )
    
    update_data = data.model_dump(exclude_unset=True)
    if update_data:
        item = await repo.update(item, update_data)
    
    return InventoryItemResponse.model_validate(item)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_inventory_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete an inventory item."""
    repo = InventoryItemRepository(db)
    
    deleted = await repo.delete(item_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Inventory item {item_id} not found"
        )


@router.post("/{item_id}/reserve", response_model=InventoryItemResponse)
async def reserve_inventory_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Reserve an available inventory item."""
    repo = InventoryItemRepository(db)
    
    item = await repo.reserve_item(item_id)
    if not item:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot reserve item {item_id} - not available or doesn't exist"
        )
    
    return InventoryItemResponse.model_validate(item)


@router.post("/{item_id}/sell", response_model=InventoryItemResponse)
async def sell_inventory_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Mark an inventory item as sold."""
    repo = InventoryItemRepository(db)
    
    item = await repo.sell_item(item_id, sold_at=datetime.now())
    if not item:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot sell item {item_id} - not available/reserved or doesn't exist"
        )
    
    return InventoryItemResponse.model_validate(item)


@router.get("/summary/{variant_id}", response_model=InventorySummary)
async def get_inventory_summary(
    variant_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get inventory count summary for a variant."""
    inventory_repo = InventoryItemRepository(db)
    variant_repo = ProductVariantRepository(db)
    
    variant = await variant_repo.get(variant_id)
    if not variant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product variant {variant_id} not found"
        )
    
    counts = await inventory_repo.count_by_status(variant_id)
    
    return InventorySummary(
        variant_id=variant_id,
        full_sku=variant.full_sku,
        available=counts.get("AVAILABLE", 0),
        sold=counts.get("SOLD", 0),
        reserved=counts.get("RESERVED", 0),
        rma=counts.get("RMA", 0),
        damaged=counts.get("DAMAGED", 0),
        total=counts.get("total", 0)
    )


@router.get("/value/total", response_model=dict)
async def get_total_inventory_value(
    variant_id: Annotated[int | None, Query(description="Filter by variant")] = None,
    status_filter: Annotated[InventoryStatus | None, Query(alias="status")] = None,
    db: AsyncSession = Depends(get_db),
):
    """Calculate total inventory value (cost basis)."""
    repo = InventoryItemRepository(db)
    
    total = await repo.get_total_value(variant_id=variant_id, status=status_filter)
    
    return {
        "total_value": total,
        "currency": "USD",
        "filters": {
            "variant_id": variant_id,
            "status": status_filter.value if status_filter else None
        }
    }


# ============================================================================
# WAREHOUSE OPERATIONS ENDPOINTS
# ============================================================================

@router.post("/receive", response_model=InventoryReceiveResponse)
async def receive_inventory(
    data: InventoryReceiveRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Receive a new inventory item via barcode scan.
    
    This endpoint is designed for warehouse operations where items are scanned
    at receiving. It creates a new inventory item with status AVAILABLE.
    
    - If variant_sku is provided, it will be used to find the variant
    - If only serial_number is provided, variant must be determined externally
    """
    inventory_repo = InventoryItemRepository(db)
    variant_repo = ProductVariantRepository(db)
    
    # Check for duplicate serial number
    existing = await inventory_repo.get_by_serial(data.serial_number)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Inventory item with serial '{data.serial_number}' already exists"
        )
    
    # Find variant by SKU if provided
    variant = None
    if data.variant_sku:
        variant = await variant_repo.get_by_sku(data.variant_sku)
        if not variant:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Product variant with SKU '{data.variant_sku}' not found"
            )
    else:
        # If no SKU provided, we need at least one variant to exist
        # For now, return an error asking for SKU
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="variant_sku is required to receive inventory"
        )
    
    # Create the inventory item
    now = datetime.now()
    item_data = {
        "serial_number": data.serial_number,
        "variant_id": variant.id,
        "status": InventoryStatus.AVAILABLE,
        "location_code": data.location_code,
        "cost_basis": data.cost_basis,
        "received_at": now,
    }
    
    item = await inventory_repo.create(item_data)
    
    return InventoryReceiveResponse(
        id=item.id,
        serial_number=item.serial_number,
        sku=variant.full_sku,
        location_code=item.location_code,
        status=item.status.value,
        received_at=item.received_at or now,
    )


@router.post("/move", response_model=InventoryMoveResponse)
async def move_inventory(
    data: InventoryMoveRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Move an inventory item to a new location.
    
    This endpoint updates the location_code of an item identified by serial number.
    """
    repo = InventoryItemRepository(db)
    
    # Find the item by serial number
    item = await repo.get_by_serial(data.serial_number)
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Inventory item with serial '{data.serial_number}' not found"
        )
    
    # Store previous location
    previous_location = item.location_code
    
    # Update location
    item = await repo.update(item, {"location_code": data.new_location})
    
    return InventoryMoveResponse(
        serial_number=item.serial_number,
        previous_location=previous_location,
        new_location=item.location_code,
        moved_at=datetime.now(),
    )


@router.get("/audit/{sku_or_serial}", response_model=InventoryAuditResponse)
async def audit_inventory(
    sku_or_serial: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Audit/lookup inventory by SKU or serial number.
    
    Returns all matching inventory items with their locations and statuses.
    This endpoint is used by warehouse operations for item lookup and
    stock verification.
    
    - If the input looks like a serial number, search by serial
    - If it looks like a SKU, search for all items of that variant
    """
    # First, try to find by serial number (exact match)
    inventory_repo = InventoryItemRepository(db)
    variant_repo = ProductVariantRepository(db)
    
    items = []
    
    # Try serial number lookup first
    item = await inventory_repo.get_by_serial(sku_or_serial)
    if item:
        # Get the variant for SKU info
        variant = await variant_repo.get(item.variant_id)
        items.append(InventoryAuditItem(
            id=item.id,
            serial_number=item.serial_number,
            location_code=item.location_code,
            status=item.status.value,
            received_at=item.received_at,
            variant_id=item.variant_id,
            full_sku=variant.full_sku if variant else None,
        ))
    else:
        # Try SKU lookup - find variant first
        variant = await variant_repo.get_by_sku(sku_or_serial)
        if variant:
            # Get all inventory items for this variant
            variant_items = await inventory_repo.get_by_variant(variant.id, limit=1000)
            for inv_item in variant_items:
                items.append(InventoryAuditItem(
                    id=inv_item.id,
                    serial_number=inv_item.serial_number,
                    location_code=inv_item.location_code,
                    status=inv_item.status.value,
                    received_at=inv_item.received_at,
                    variant_id=inv_item.variant_id,
                    full_sku=variant.full_sku,
                ))
    
    return InventoryAuditResponse(
        items=items,
        total_count=len(items),
    )
