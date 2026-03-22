"""
Order Sync Service – the "Safe Sync" engine.

Implements MOD-002-ORD §4: State-aware synchronization with:
  1. Sync-lock via IntegrationState
  2. 10-minute overlap buffer
  3. Auto-match via PLATFORM_LISTING
  4. Idempotent insert (skip duplicates)
  5. Atomic state commit on success / error capture on failure

Also implements manual Match & Learn, Confirm, and Reject actions.
"""
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.base import BasePlatformClient, ExternalOrder, ExternalOrderItem
from app.models.entities import Platform, PlatformListing, Customer
from app.modules.orders.models import (
    IntegrationSyncStatus,
    Order,
    OrderItem,
    OrderItemStatus,
    OrderPlatform,
    OrderStatus,
)
from app.modules.orders.schemas.sync import SyncResponse
from app.repositories.inventory import PlatformListingRepository
from app.repositories.orders.order_repository import OrderItemRepository, OrderRepository
from app.repositories.orders.sync_repository import SyncRepository

logger = logging.getLogger(__name__)

# Mapping from IntegrationState platform_name → OrderPlatform enum
_PLATFORM_MAP: dict[str, OrderPlatform] = {
    "AMAZON": OrderPlatform.AMAZON,
    "EBAY_MEKONG": OrderPlatform.EBAY_MEKONG,
    "EBAY_USAV": OrderPlatform.EBAY_USAV,
    "EBAY_DRAGON": OrderPlatform.EBAY_DRAGON,
    "ECWID": OrderPlatform.ECWID,
}

# Mapping from OrderPlatform → entities.Platform (for PLATFORM_LISTING lookups)
_ORDER_TO_ENTITY_PLATFORM: dict[OrderPlatform, Platform] = {
    OrderPlatform.AMAZON: Platform.AMAZON,
    OrderPlatform.EBAY_MEKONG: Platform.EBAY_MEKONG,
    OrderPlatform.EBAY_USAV: Platform.EBAY_USAV,
    OrderPlatform.EBAY_DRAGON: Platform.EBAY_DRAGON,
    OrderPlatform.ECWID: Platform.ECWID,
}

SYNC_BUFFER_MINUTES = 10


class OrderSyncService:
    """
    Orchestrates order ingestion from external platforms.

    Instantiated per-request – receives an ``AsyncSession`` and the
    relevant repository instances via dependency injection.
    """

    def __init__(
        self,
        session: AsyncSession,
        sync_repo: SyncRepository,
        order_repo: OrderRepository,
        order_item_repo: OrderItemRepository,
        listing_repo: PlatformListingRepository,
    ):
        self.session = session
        self.sync_repo = sync_repo
        self.order_repo = order_repo
        self.order_item_repo = order_item_repo
        self.listing_repo = listing_repo

    # ------------------------------------------------------------------
    # PUBLIC – Sync entry point
    # ------------------------------------------------------------------

    async def sync_platform(
        self,
        platform_name: str,
        client: BasePlatformClient,
    ) -> SyncResponse:
        """
        Execute the "Safe Sync" workflow for a single platform.

        Steps:
          1. Acquire sync lock (IDLE → SYNCING).
          2. Calculate fetch window with 10-min buffer.
          3. Fetch orders from the external client.
          4. Ingest orders idempotently (skip duplicates).
          5. Auto-match items via PLATFORM_LISTING.
          6. Commit state on success / capture error on failure.
        """
        logger.info(f"=== Starting sync_platform for {platform_name} ===")
        response = SyncResponse(platform=platform_name)

        # Step 1 – acquire lock
        logger.info(f"{platform_name}: Attempting to acquire sync lock")
        locked = await self.sync_repo.acquire_sync_lock(platform_name)
        logger.info(f"{platform_name}: Lock acquired={locked}")
        if not locked:
            response.success = False
            error_msg = f"Platform '{platform_name}' is currently syncing or in error. Reset the state before retrying."
            logger.warning(f"{platform_name}: {error_msg}")
            response.errors.append(error_msg)
            return response

        try:
            # Step 2 – determine fetch window
            logger.info(f"{platform_name}: Retrieving integration state")
            state = await self.sync_repo.get_by_platform(platform_name)
            last_sync = state.last_successful_sync if state else None
            logger.info(f"{platform_name}: Last successful sync = {last_sync}")
            if last_sync is None:
                # Never synced – use a sensible default
                fetch_since = datetime(2026, 1, 1, tzinfo=timezone.utc)
                logger.info(f"{platform_name}: Never synced before, using default anchor: {fetch_since}")
            else:
                fetch_since = last_sync - timedelta(minutes=SYNC_BUFFER_MINUTES)
                logger.info(f"{platform_name}: Using last_sync minus {SYNC_BUFFER_MINUTES}min buffer: {fetch_since}")

            logger.info(
                "%s: Calling client.fetch_orders(since=%s)",
                platform_name,
                fetch_since.isoformat(),
            )

            # Step 3 – call external adapter
            external_orders: list[ExternalOrder] = await client.fetch_orders(
                since=fetch_since,
            )
            logger.info(
                "%s: Adapter returned %d orders",
                platform_name,
                len(external_orders),
            )

            # Step 4 – ingest
            order_platform = _PLATFORM_MAP.get(platform_name)
            logger.info(f"{platform_name}: Mapped to order platform enum: {order_platform}")
            if order_platform is None:
                raise ValueError(f"Unknown platform mapping for '{platform_name}'")

            logger.info(f"{platform_name}: Starting ingestion of {len(external_orders)} orders")
            for idx, ext_order in enumerate(external_orders, 1):
                logger.debug(f"{platform_name}: Ingesting order {idx}/{len(external_orders)}: {ext_order.platform_order_id}")
                was_new = await self._ingest_order(ext_order, order_platform, response)
                if not was_new:
                    response.skipped_duplicates += 1
                    logger.debug(f"{platform_name}: Order {ext_order.platform_order_id} was duplicate, skipped")

            # Step 5 – mark success & update anchor
            logger.info(f"{platform_name}: Ingestion complete, releasing lock and marking success")
            await self.sync_repo.release_sync_success(platform_name)
            await self.session.commit()
            logger.info(f"{platform_name}: Sync completed successfully")

        except Exception as exc:
            await self.session.rollback()
            error_msg = f"{type(exc).__name__}: {exc}"
            logger.exception("=== Sync %s FAILED ===: %s", platform_name, error_msg)
            logger.error(f"{platform_name}: Exception details:", exc_info=True)
            # Re-acquire a fresh session state for the error update
            logger.info(f"{platform_name}: Releasing lock and marking ERROR state")
            await self.sync_repo.release_sync_error(platform_name, error_msg)
            await self.session.commit()
            response.success = False
            response.errors.append(error_msg)

        return response

    # ------------------------------------------------------------------
    # PUBLIC – Admin date-range sync (no lock, caller-supplied window)
    # ------------------------------------------------------------------

    async def sync_platform_range(
        self,
        platform_name: str,
        client: BasePlatformClient,
        since: datetime,
        until: datetime,
    ) -> SyncResponse:
        """
        Fetch orders within an explicit date range.

        Unlike ``sync_platform``, this does **not** acquire a sync lock or
        update the IntegrationState anchor.  Deduplication still applies:
        orders already in the database are silently skipped.
        """
        logger.info(
            "=== Admin range sync for %s  [%s → %s] ===",
            platform_name, since.isoformat(), until.isoformat(),
        )
        response = SyncResponse(platform=platform_name)

        try:
            external_orders: list[ExternalOrder] = await client.fetch_orders(
                since=since, until=until,
            )
            logger.info("%s: Adapter returned %d orders", platform_name, len(external_orders))

            order_platform = _PLATFORM_MAP.get(platform_name)
            if order_platform is None:
                raise ValueError(f"Unknown platform mapping for '{platform_name}'")

            for ext_order in external_orders:
                was_new = await self._ingest_order(ext_order, order_platform, response)
                if not was_new:
                    response.skipped_duplicates += 1

            await self.session.commit()
            logger.info("%s: Range sync completed successfully", platform_name)

        except Exception as exc:
            await self.session.rollback()
            error_msg = f"{type(exc).__name__}: {exc}"
            logger.exception("=== Range sync %s FAILED ===: %s", platform_name, error_msg)
            response.success = False
            response.errors.append(error_msg)

        return response

    # ------------------------------------------------------------------
    # PUBLIC – Manual Match & Learn
    # ------------------------------------------------------------------

    async def match_item(
        self,
        item_id: int,
        variant_id: int,
        *,
        learn: bool = True,
        notes: Optional[str] = None,
    ) -> OrderItem:
        """
        Manually link an order item to an internal variant.

        If ``learn=True``, also upserts a ``PLATFORM_LISTING`` row so the same
        external reference is auto-matched on future syncs.
        """
        item = await self.order_item_repo.get(item_id)
        if item is None:
            raise ValueError(f"OrderItem {item_id} not found")

        # Update the item
        item.variant_id = variant_id
        item.status = OrderItemStatus.MATCHED
        if notes:
            item.matching_notes = notes
        self.session.add(item)

        # "Learn" – persist the mapping in PLATFORM_LISTING
        if learn:
            await self._learn_listing(item, variant_id)

        await self.session.flush()
        await self.session.refresh(item)
        return item

    async def confirm_item(self, item_id: int, notes: Optional[str] = None) -> OrderItem:
        """Confirm an auto-matched item – no DB change needed beyond status."""
        item = await self.order_item_repo.get(item_id)
        if item is None:
            raise ValueError(f"OrderItem {item_id} not found")
        if item.status != OrderItemStatus.MATCHED:
            raise ValueError(
                f"Item {item_id} is '{item.status.value}', expected MATCHED."
            )
        if notes:
            item.matching_notes = notes
        # Status stays MATCHED (confirmed). We could add an ALLOCATED step later.
        self.session.add(item)
        await self.session.flush()
        await self.session.refresh(item)
        return item

    async def reject_item(self, item_id: int, notes: Optional[str] = None) -> OrderItem:
        """
        Reject a bad auto-match – reset item to UNMATCHED.

        Does NOT remove the PLATFORM_LISTING row (the mapping may be correct
        for other items; an admin can clean up listings separately).
        """
        item = await self.order_item_repo.get(item_id)
        if item is None:
            raise ValueError(f"OrderItem {item_id} not found")

        item.variant_id = None
        item.status = OrderItemStatus.UNMATCHED
        item.matching_notes = notes or "Auto-match rejected by user."
        self.session.add(item)
        await self.session.flush()
        await self.session.refresh(item)
        return item

    # ------------------------------------------------------------------
    # PRIVATE – Ingestion helpers
    # ------------------------------------------------------------------

    async def _ingest_order(
        self,
        ext: ExternalOrder,
        platform: OrderPlatform,
        response: SyncResponse,
    ) -> bool:
        """
        Insert a single external order + items.

        Returns True if the order was new, False if it was a duplicate.
        """
        # Deduplication check
        existing = await self.order_repo.get_by_external_id(
            platform, ext.platform_order_id,
        )
        if existing is not None:
            return False

        # Upsert/lookup Customer (if any data is available)
        customer_id = await self._get_or_create_customer(ext)

        # Build the Order header
        order_data = {
            "platform": platform,
            "external_order_id": ext.platform_order_id,
            "external_order_number": ext.platform_order_number,
            "status": OrderStatus.PENDING,
            "customer_id": customer_id,
            "customer_name": ext.customer_name,
            "customer_email": ext.customer_email,
            "shipping_address_line1": ext.ship_address_line1,
            "shipping_address_line2": ext.ship_address_line2,
            "shipping_city": ext.ship_city,
            "shipping_state": ext.ship_state,
            "shipping_postal_code": ext.ship_postal_code,
            "shipping_country": ext.ship_country or "US",
            "subtotal_amount": Decimal(str(ext.subtotal)),
            "tax_amount": Decimal(str(ext.tax)),
            "shipping_amount": Decimal(str(ext.shipping)),
            "total_amount": Decimal(str(ext.total)),
            "currency": ext.currency or "USD",
            "ordered_at": ext.ordered_at,
            "platform_data": ext.raw_data,
        }

        try:
            order = await self.order_repo.create(order_data)
        except IntegrityError:
            # Race condition – another request inserted the same order
            await self.session.rollback()
            return False

        response.new_orders += 1

        # Insert line items with auto-match
        for ext_item in ext.items:
            await self._ingest_item(ext_item, order, platform, response)

        return True

    async def _get_or_create_customer(self, ext: ExternalOrder) -> Optional[int]:
        """Find or create a Customer from external order details."""
        if not (ext.customer_name or ext.customer_email):
            return None

        # Prefer email for deterministic matching
        if ext.customer_email:
            existing = await self.session.execute(
                select(Customer).where(Customer.email == ext.customer_email)
            )
            customer = existing.scalar_one_or_none()
            if customer:
                return customer.id

        # Fallback: match by name + postal code if available
        if ext.customer_name:
            query = select(Customer).where(Customer.name == ext.customer_name)
            if ext.ship_postal_code:
                query = query.where(Customer.postal_code == ext.ship_postal_code)
            existing = await self.session.execute(query)
            customer = existing.scalar_one_or_none()
            if customer:
                return customer.id

        # Create new customer
        customer = Customer(
            name=ext.customer_name or "Unknown",
            email=ext.customer_email,
            phone=None,
            company_name=None,
            address_line1=ext.ship_address_line1,
            address_line2=ext.ship_address_line2,
            city=ext.ship_city,
            state=ext.ship_state,
            postal_code=ext.ship_postal_code,
            country=ext.ship_country or "US",
            is_active=True,
        )
        self.session.add(customer)
        await self.session.flush()
        return customer.id

    async def _ingest_item(
        self,
        ext_item: ExternalOrderItem,
        order: Order,
        platform: OrderPlatform,
        response: SyncResponse,
    ) -> None:
        """Insert one line item and attempt auto-match."""
        # Auto-match: look up external ref in PLATFORM_LISTING
        variant_id: Optional[int] = None
        item_status = OrderItemStatus.UNMATCHED

        entity_platform = _ORDER_TO_ENTITY_PLATFORM.get(platform)
        if entity_platform and ext_item.platform_item_id:
            listing = await self.listing_repo.get_active_by_external_ref(
                entity_platform, ext_item.platform_item_id,
            )
            if listing is not None:
                variant_id = listing.variant_id
                item_status = OrderItemStatus.MATCHED
                response.auto_matched += 1

        # Fallback: try matching by platform SKU
        if variant_id is None and entity_platform and ext_item.platform_sku:
            listing = await self.listing_repo.get_active_by_external_ref(
                entity_platform, ext_item.platform_sku,
            )
            if listing is not None:
                variant_id = listing.variant_id
                item_status = OrderItemStatus.MATCHED
                response.auto_matched += 1

        # Fallback: try matching by item name against platform listing titles
        if variant_id is None and entity_platform and ext_item.title:
            listing = await self.listing_repo.search_active_by_listed_name(
                entity_platform, ext_item.title,
            )
            if listing is not None:
                variant_id = listing.variant_id
                item_status = OrderItemStatus.MATCHED
                response.auto_matched += 1
                logger.info(
                    "Name-matched item '%s' → variant %d via listing '%s'",
                    ext_item.title, variant_id, listing.listed_name,
                )

        item_data = {
            "order_id": order.id,
            "external_item_id": ext_item.platform_item_id,
            "external_sku": ext_item.platform_sku,
            "external_asin": ext_item.asin,
            "variant_id": variant_id,
            "status": item_status,
            "item_name": ext_item.title,
            "quantity": ext_item.quantity,
            "unit_price": Decimal(str(ext_item.unit_price)),
            "total_price": Decimal(str(ext_item.total_price)),
            "item_metadata": ext_item.raw_data,
        }
        await self.order_item_repo.create(item_data)
        response.new_items += 1

    async def _learn_listing(self, item: OrderItem, variant_id: int) -> None:
        """
        Create (or silently skip) a PLATFORM_LISTING row to teach the
        auto-match engine for future orders.

        Also serves as the "auto-create listing on manual match" path:
        whenever a user manually matches an order item, a listing is
        created with the item's name, price, and external identifiers
        so that future orders are auto-matched.
        """
        order = await self.order_repo.get(item.order_id)
        if order is None:
            return

        entity_platform = _ORDER_TO_ENTITY_PLATFORM.get(order.platform)
        if entity_platform is None:
            return

        ext_ref = item.external_item_id or item.external_sku

        # Check if a listing already exists for this variant+platform
        existing = await self.listing_repo.get_by_variant_platform(
            variant_id, entity_platform,
        )
        if existing is not None:
            # Update with richer data if missing
            changed = False
            if not existing.external_ref_id and ext_ref:
                existing.external_ref_id = ext_ref
                changed = True
            if not existing.listed_name and item.item_name:
                existing.listed_name = item.item_name
                changed = True
            if not existing.listing_price and item.unit_price:
                existing.listing_price = item.unit_price
                changed = True
            if changed:
                self.session.add(existing)
                try:
                    await self.session.flush()
                except IntegrityError:
                    await self.session.rollback()
            return

        # Also check by external_ref_id to avoid duplicate ref conflicts
        if ext_ref:
            ref_existing = await self.listing_repo.get_by_external_ref(
                entity_platform, ext_ref,
            )
            if ref_existing is not None:
                return  # Already mapped to a different variant

        listing = PlatformListing(
            variant_id=variant_id,
            platform=entity_platform,
            external_ref_id=ext_ref,
            listed_name=item.item_name,
            listing_price=item.unit_price,
        )
        self.session.add(listing)
        try:
            await self.session.flush()
        except IntegrityError:
            # Another concurrent request already created this listing
            await self.session.rollback()
