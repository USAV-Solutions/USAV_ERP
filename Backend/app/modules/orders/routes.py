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
import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.integrations.amazon.client import AmazonClient
from app.integrations.base import BasePlatformClient
from app.integrations.ebay.client import EbayClient
from app.integrations.ecwid.client import EcwidClient
from app.modules.orders.dependencies import (
    get_order_item_repo,
    get_order_repo,
    get_order_sync_service,
    get_sync_repo,
)
from app.modules.orders.models import OrderItemStatus, OrderPlatform
from app.modules.orders.schemas.orders import (
    OrderBrief,
    OrderDetail,
    OrderItemBrief,
    OrderItemConfirmRequest,
    OrderItemDetail,
    OrderItemMatchRequest,
    OrderListResponse,
    OrderStatusUpdate,
)
from app.modules.orders.schemas.sync import (
    IntegrationStateResponse,
    SyncRangeRequest,
    SyncRequest,
    SyncResponse,
    SyncStatusResponse,
)
from app.modules.orders.service import OrderSyncService
from app.repositories.orders.order_repository import OrderItemRepository, OrderRepository
from app.repositories.orders.sync_repository import SyncRepository
from app.api.deps import AdminUser

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/orders", tags=["Orders"])


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

    logger.info(f"Platform clients built: {list(clients.keys())}")
    return clients


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
    logger.info(f"Sync orders endpoint called: platform={body.platform}")
    clients = _build_platform_clients()
    logger.info(f"Available clients: {list(clients.keys())}")

    if body.platform:
        # Single platform
        logger.info(f"Single platform sync requested: {body.platform}")
        if body.platform not in clients:
            logger.error(f"Platform '{body.platform}' not in available clients {list(clients.keys())}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Platform '{body.platform}' is not configured or unknown.",
            )
        logger.info(f"Starting sync for {body.platform}")
        result = await service.sync_platform(body.platform, clients[body.platform])
        logger.info(f"Sync result for {body.platform}: success={result.success}, new={result.new_orders}, errors={result.errors}")
        return [result]

    # All platforms
    logger.info(f"Syncing all platforms: {list(clients.keys())}")
    results: list[SyncResponse] = []
    for name, client in clients.items():
        logger.info(f"Starting sync for platform: {name}")
        result = await service.sync_platform(name, client)
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
    logger.info(
        "Admin range sync: platform=%s  since=%s  until=%s",
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
            body.platform, clients[body.platform], body.since, body.until,
        )
        return [result]

    results: list[SyncResponse] = []
    for name, client in clients.items():
        result = await service.sync_platform_range(
            name, client, body.since, body.until,
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
    search: Annotated[Optional[str], Query()] = None,
    order_repo: OrderRepository = Depends(get_order_repo),
):
    """
    **The Dashboard.**

    Paginated order list with optional filters for platform, status,
    item-level status (e.g. UNMATCHED), and free-text search.
    """
    from app.modules.orders.models import OrderStatus as OS

    os_filter = None
    if status_filter:
        try:
            os_filter = OS(status_filter)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid order status: {status_filter}",
            )

    orders, total = await order_repo.list_orders(
        skip=skip,
        limit=limit,
        platform=platform,
        status=os_filter,
        item_status=item_status,
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
                external_order_id=o.external_order_id,
                external_order_number=o.external_order_number,
                status=o.status,
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
