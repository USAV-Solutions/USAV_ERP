"""
Order API Routes.

Handles all order-related HTTP endpoints.
"""
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.inventory.schemas import PaginatedResponse
from app.modules.orders.models import OrderPlatform, OrderStatus, OrderItemStatus
from app.modules.orders.schemas import (
    OrderCreate,
    OrderResponse,
    OrderUpdate,
    OrderWithItems,
    OrderItemUpdate,
    OrderItemResponse,
    OrderSummary,
    SkuMatchRequest,
    BulkSkuMatchRequest,
    InventoryAllocationRequest,
    BulkInventoryAllocationRequest,
)
from app.modules.orders.services import OrderService

router = APIRouter(prefix="/orders", tags=["Orders"])


# ============================================================================
# ORDER CRUD ENDPOINTS
# ============================================================================

@router.get("", response_model=PaginatedResponse)
async def list_orders(
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    status_filter: Annotated[OrderStatus | None, Query(alias="status")] = None,
    platform: Annotated[OrderPlatform | None, Query()] = None,
    db: AsyncSession = Depends(get_db),
):
    """List orders with optional filtering."""
    service = OrderService(db)
    
    orders = await service.list_orders(
        skip=skip,
        limit=limit,
        status=status_filter,
        platform=platform,
    )
    total = await service.count_orders(status=status_filter, platform=platform)
    
    return PaginatedResponse(
        total=total,
        skip=skip,
        limit=limit,
        items=[OrderResponse.model_validate(order) for order in orders]
    )


@router.post("", response_model=OrderWithItems, status_code=status.HTTP_201_CREATED)
async def create_order(
    data: OrderCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new order.
    
    Items will be auto-matched to internal SKUs if possible.
    """
    service = OrderService(db)
    
    # Check for duplicate
    existing = await service.get_order_by_external_id(data.platform, data.external_order_id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Order {data.external_order_id} on {data.platform.value} already exists"
        )
    
    order_data = data.model_dump(exclude={"items"})
    items_data = [item.model_dump() for item in data.items]
    
    order = await service.process_incoming_order(order_data, items_data)
    return OrderWithItems.model_validate(order)


@router.get("/summary", response_model=OrderSummary)
async def get_order_summary(
    db: AsyncSession = Depends(get_db),
):
    """Get summary statistics for all orders."""
    service = OrderService(db)
    summary = await service.get_order_summary()
    return OrderSummary(**summary)


@router.get("/{order_id}", response_model=OrderWithItems)
async def get_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get a specific order with all items."""
    service = OrderService(db)
    order = await service.get_order(order_id)
    
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order {order_id} not found"
        )
    
    return OrderWithItems.model_validate(order)


@router.put("/{order_id}", response_model=OrderResponse)
@router.patch("/{order_id}", response_model=OrderResponse)
async def update_order(
    order_id: int,
    data: OrderUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update order status, tracking, etc. (supports both PUT and PATCH)."""
    service = OrderService(db)
    order = await service.get_order(order_id)
    
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order {order_id} not found"
        )
    
    update_data = data.model_dump(exclude_unset=True)
    
    # Apply updates
    for key, value in update_data.items():
        setattr(order, key, value)
    
    await db.flush()
    return OrderResponse.model_validate(order)


# ============================================================================
# ORDER STATUS MANAGEMENT
# ============================================================================

@router.post("/{order_id}/process", response_model=OrderResponse)
async def mark_order_processing(
    order_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Mark an order as processing."""
    service = OrderService(db)
    order = await service.update_order_status(order_id, OrderStatus.PROCESSING)
    
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order {order_id} not found"
        )
    
    return OrderResponse.model_validate(order)


@router.post("/{order_id}/ready-to-ship", response_model=OrderResponse)
async def mark_order_ready_to_ship(
    order_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Mark an order as ready to ship."""
    service = OrderService(db)
    order = await service.get_order(order_id)
    
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order {order_id} not found"
        )
    
    # Check if all items are allocated
    unallocated = [i for i in order.items if i.status != OrderItemStatus.ALLOCATED]
    if unallocated:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{len(unallocated)} item(s) not yet allocated"
        )
    
    order = await service.update_order_status(order_id, OrderStatus.READY_TO_SHIP)
    return OrderResponse.model_validate(order)


@router.post("/{order_id}/ship", response_model=OrderResponse)
async def mark_order_shipped(
    order_id: int,
    tracking_number: str = None,
    carrier: str = None,
    db: AsyncSession = Depends(get_db),
):
    """Mark an order as shipped with optional tracking info."""
    service = OrderService(db)
    order = await service.get_order(order_id)
    
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order {order_id} not found"
        )
    
    if tracking_number:
        order.tracking_number = tracking_number
    if carrier:
        order.carrier = carrier
    
    order = await service.update_order_status(order_id, OrderStatus.SHIPPED)
    
    # Update all items to shipped
    for item in order.items:
        item.status = OrderItemStatus.SHIPPED
    
    await db.flush()
    return OrderResponse.model_validate(order)


@router.post("/{order_id}/cancel", response_model=OrderResponse)
async def cancel_order(
    order_id: int,
    notes: str = None,
    db: AsyncSession = Depends(get_db),
):
    """Cancel an order and release allocated inventory."""
    service = OrderService(db)
    order = await service.get_order(order_id)
    
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order {order_id} not found"
        )
    
    if order.status == OrderStatus.SHIPPED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot cancel a shipped order"
        )
    
    # Release allocated inventory
    from app.models.entities import InventoryItem, InventoryStatus
    for item in order.items:
        if item.allocated_inventory_id:
            inventory = await db.get(InventoryItem, item.allocated_inventory_id)
            if inventory and inventory.status == InventoryStatus.RESERVED:
                inventory.status = InventoryStatus.AVAILABLE
            item.allocated_inventory_id = None
        item.status = OrderItemStatus.CANCELLED
    
    order = await service.update_order_status(
        order_id, 
        OrderStatus.CANCELLED,
        notes=notes
    )
    
    await db.flush()
    return OrderResponse.model_validate(order)


# ============================================================================
# SKU MATCHING ENDPOINTS
# ============================================================================

@router.get("/items/unmatched", response_model=list[OrderItemResponse])
async def get_unmatched_items(
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    db: AsyncSession = Depends(get_db),
):
    """Get all order items that need SKU matching."""
    from sqlalchemy import select
    from app.modules.orders.models import OrderItem
    
    result = await db.execute(
        select(OrderItem)
        .where(OrderItem.status == OrderItemStatus.UNMATCHED)
        .order_by(OrderItem.created_at.desc())
        .limit(limit)
    )
    items = result.scalars().all()
    
    return [OrderItemResponse.model_validate(item) for item in items]


@router.post("/items/{item_id}/match", response_model=OrderItemResponse)
async def match_item_sku(
    item_id: int,
    variant_id: int,
    notes: str = None,
    db: AsyncSession = Depends(get_db),
):
    """Manually match an order item to a product variant."""
    service = OrderService(db)
    item = await service.match_sku_manually(item_id, variant_id, notes)
    
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Item or variant not found"
        )
    
    return OrderItemResponse.model_validate(item)


@router.post("/items/match-bulk", response_model=list[OrderItemResponse])
async def bulk_match_skus(
    request: BulkSkuMatchRequest,
    db: AsyncSession = Depends(get_db),
):
    """Match multiple order items to variants at once."""
    service = OrderService(db)
    results = []
    
    for match in request.matches:
        item = await service.match_sku_manually(
            match.order_item_id,
            match.variant_id,
            match.notes
        )
        if item:
            results.append(OrderItemResponse.model_validate(item))
    
    return results


# ============================================================================
# INVENTORY ALLOCATION ENDPOINTS
# ============================================================================

@router.post("/items/{item_id}/allocate", response_model=OrderItemResponse)
async def allocate_inventory_to_item(
    item_id: int,
    inventory_item_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Allocate a specific inventory item to an order item."""
    service = OrderService(db)
    item = await service.allocate_inventory(item_id, inventory_item_id)
    
    if not item:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot allocate: item not found, inventory not available, or SKU mismatch"
        )
    
    return OrderItemResponse.model_validate(item)


@router.post("/items/allocate-bulk", response_model=list[OrderItemResponse])
async def bulk_allocate_inventory(
    request: BulkInventoryAllocationRequest,
    db: AsyncSession = Depends(get_db),
):
    """Allocate inventory to multiple order items at once."""
    service = OrderService(db)
    results = []
    
    for allocation in request.allocations:
        item = await service.allocate_inventory(
            allocation.order_item_id,
            allocation.inventory_item_id
        )
        if item:
            results.append(OrderItemResponse.model_validate(item))
    
    return results


# ============================================================================
# ORDER SYNC ENDPOINTS
# ============================================================================

@router.post("/sync/{platform}")
async def sync_orders_from_platform(
    platform: OrderPlatform,
    order_date: Annotated[date, Query(description="Date to fetch orders from (YYYY-MM-DD)")] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Sync orders from an external platform for a specific date.
    
    Supported platforms:
    - EBAY_MEKONG
    - EBAY_USAV
    - EBAY_DRAGON
    - ECWID
    
    Args:
        platform: The platform to sync from
        order_date: Date to fetch orders (defaults to today)
    
    Returns:
        Sync result with counts of new, existing, and errored orders
    """
    # Validate platform
    supported_platforms = [
        OrderPlatform.EBAY_MEKONG,
        OrderPlatform.EBAY_USAV,
        OrderPlatform.EBAY_DRAGON,
        OrderPlatform.ECWID,
    ]
    
    if platform not in supported_platforms:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Platform {platform.value} not supported for sync. "
                   f"Supported: {[p.value for p in supported_platforms]}"
        )
    
    # Default to today if no date provided
    if order_date is None:
        from datetime import date as date_module
        order_date = date_module.today()
    
    # Sync orders
    service = OrderService(db)
    
    try:
        result = await service.sync_orders_from_platform(platform, order_date)
        return {
            "success": True,
            "platform": platform.value,
            "date": order_date.isoformat(),
            **result,
        }
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error syncing orders: {str(e)}"
        )
