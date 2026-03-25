"""
Manual "Force Sync" endpoints.

Allow frontend users to trigger a Zoho sync for a specific record on demand,
bypassing the automatic SQLAlchemy event listeners.  Every endpoint returns
``202 Accepted`` immediately – the actual work runs in the background.
"""
from datetime import date
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import AdminUser, CurrentUser
from app.core.database import get_db
from app.integrations.zoho.sync_engine import (
    sync_po_outbound,
    sync_customer_outbound,
    sync_order_outbound,
    sync_variant_outbound,
)
from app.models.purchasing import PurchaseOrder
from app.models.entities import Customer, ProductVariant, ZohoSyncStatus
from app.modules.orders.models import Order

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sync", tags=["Zoho Sync"])


# ------------------------------------------------------------------
# Items (ProductVariant → Zoho Item)
# ------------------------------------------------------------------

@router.post(
    "/items/{variant_id}",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Force-sync a product variant to Zoho",
)
async def force_sync_item(
    variant_id: int,
    background_tasks: BackgroundTasks,
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """
    Queue an outbound Zoho sync for the given ``ProductVariant``.

    Returns **202 Accepted** immediately; the sync runs in the background.
    """
    variant = (
        await db.execute(
            select(ProductVariant).where(ProductVariant.id == variant_id)
        )
    ).scalar_one_or_none()

    if variant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Variant {variant_id} not found.",
        )
    if not variant.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Variant {variant_id} is inactive.",
        )

    background_tasks.add_task(sync_variant_outbound, variant_id)

    logger.info("Force-sync queued | entity=variant id=%s user=%s", variant_id, _admin.id)
    return {"status": "queued", "entity": "variant", "id": variant_id}


# ------------------------------------------------------------------
# Orders (Order → Zoho SalesOrder)
# ------------------------------------------------------------------

@router.post(
    "/orders/{order_id}",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Force-sync an order to Zoho",
)
async def force_sync_order(
    order_id: int,
    background_tasks: BackgroundTasks,
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """
    Queue an outbound Zoho sync for the given ``Order``.

    The background worker will perform dependency checks (Customer and
    ProductVariant Zoho IDs) before pushing.

    Returns **202 Accepted** immediately.
    """
    order = (
        await db.execute(select(Order).where(Order.id == order_id))
    ).scalar_one_or_none()

    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order {order_id} not found.",
        )

    background_tasks.add_task(sync_order_outbound, order_id)

    logger.info("Force-sync queued | entity=order id=%s user=%s", order_id, _admin.id)
    return {"status": "queued", "entity": "order", "id": order_id}


# ------------------------------------------------------------------
# Purchase Orders (PurchaseOrder -> Zoho PurchaseOrder)
# ------------------------------------------------------------------

@router.post(
    "/purchases/{po_id}",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Force-sync a purchase order to Zoho",
)
async def force_sync_purchase_order(
    po_id: int,
    background_tasks: BackgroundTasks,
    _current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """
    Queue outbound Zoho sync for a ``PurchaseOrder``.

    Unmatched lines are allowed; outbound sync maps them to a placeholder item.
    """
    purchase_order = (
        await db.execute(
            select(PurchaseOrder)
            .options(selectinload(PurchaseOrder.items))
            .where(PurchaseOrder.id == po_id)
        )
    ).scalar_one_or_none()

    if purchase_order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Purchase order {po_id} not found.",
        )

    if not purchase_order.items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Purchase order {po_id} has no items to sync.",
        )

    purchase_order.zoho_sync_status = ZohoSyncStatus.PENDING
    purchase_order.zoho_sync_error = None
    purchase_order._updated_by_sync = True
    await db.commit()

    background_tasks.add_task(sync_po_outbound, po_id)

    logger.info("Force-sync queued | entity=purchase id=%s user=%s", po_id, _current_user.id)
    return {"status": "queued", "entity": "purchase", "id": po_id}


@router.post(
    "/purchases",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Force-sync purchase orders in a date range to Zoho",
)
async def force_sync_purchase_orders_by_period(
    background_tasks: BackgroundTasks,
    _current_user: CurrentUser,
    order_date_from: date | None = Query(default=None),
    order_date_to: date | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2000),
    db: AsyncSession = Depends(get_db),
):
    """
    Queue outbound Zoho sync for purchase orders within an order-date window.

    If no dates are provided, the latest orders are selected up to ``limit``.
    """
    if order_date_from and order_date_to and order_date_from > order_date_to:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="order_date_from must be less than or equal to order_date_to.",
        )

    stmt = (
        select(PurchaseOrder)
        .options(selectinload(PurchaseOrder.items))
        .order_by(PurchaseOrder.order_date.desc(), PurchaseOrder.id.desc())
        .limit(limit)
    )
    if order_date_from is not None:
        stmt = stmt.where(PurchaseOrder.order_date >= order_date_from)
    if order_date_to is not None:
        stmt = stmt.where(PurchaseOrder.order_date <= order_date_to)

    purchase_orders = (await db.execute(stmt)).scalars().all()
    if not purchase_orders:
        return {
            "status": "queued",
            "entity": "purchase",
            "count": 0,
            "ids": [],
        }

    queued_ids: list[int] = []
    for po in purchase_orders:
        if not po.items:
            continue
        po.zoho_sync_status = ZohoSyncStatus.PENDING
        po.zoho_sync_error = None
        po._updated_by_sync = True
        queued_ids.append(po.id)
        background_tasks.add_task(sync_po_outbound, po.id)

    await db.commit()

    logger.info(
        "Force-sync queued | entity=purchase period from=%s to=%s count=%s user=%s",
        order_date_from,
        order_date_to,
        len(queued_ids),
        _current_user.id,
    )
    return {
        "status": "queued",
        "entity": "purchase",
        "count": len(queued_ids),
        "ids": queued_ids,
    }


# ------------------------------------------------------------------
# Customers (Customer → Zoho Contact)
# ------------------------------------------------------------------

@router.post(
    "/customers/{customer_id}",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Force-sync a customer to Zoho",
)
async def force_sync_customer(
    customer_id: int,
    background_tasks: BackgroundTasks,
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """
    Queue an outbound Zoho sync for the given ``Customer``.

    Returns **202 Accepted** immediately.
    """
    customer = (
        await db.execute(select(Customer).where(Customer.id == customer_id))
    ).scalar_one_or_none()

    if customer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Customer {customer_id} not found.",
        )

    background_tasks.add_task(sync_customer_outbound, customer_id)

    logger.info("Force-sync queued | entity=customer id=%s user=%s", customer_id, _admin.id)
    return {"status": "queued", "entity": "customer", "id": customer_id}
