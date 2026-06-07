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
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.base import BasePlatformClient, ExternalOrder, ExternalOrderItem
from app.models.entities import Platform, PlatformListing, Customer
from app.modules.orders.models import (
    IntegrationSyncStatus,
    Order,
    OrderFulfillmentChannel,
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

_NON_BLOCKING_AUTH_ERROR_MARKERS = (
    "unable to obtain access token",
    "credentials not configured",
)

# Mapping from IntegrationState platform_name → OrderPlatform enum
_PLATFORM_MAP: dict[str, OrderPlatform] = {
    "AMAZON": OrderPlatform.AMAZON,
    "EBAY_MEKONG": OrderPlatform.EBAY_MEKONG,
    "EBAY_USAV": OrderPlatform.EBAY_USAV,
    "EBAY_DRAGON": OrderPlatform.EBAY_DRAGON,
    "ECWID": OrderPlatform.ECWID,
    "SHOPIFY": OrderPlatform.SHOPIFY,
    "WALMART": OrderPlatform.WALMART,
    "MANUAL": OrderPlatform.MANUAL,
}

# Mapping from OrderPlatform → entities.Platform (for PLATFORM_LISTING lookups)
_ORDER_TO_ENTITY_PLATFORM: dict[OrderPlatform, Platform] = {
    OrderPlatform.AMAZON: Platform.AMAZON,
    OrderPlatform.EBAY_MEKONG: Platform.EBAY_MEKONG,
    OrderPlatform.EBAY_USAV: Platform.EBAY_USAV,
    OrderPlatform.EBAY_DRAGON: Platform.EBAY_DRAGON,
    OrderPlatform.ECWID: Platform.ECWID,
    OrderPlatform.WALMART: Platform.WALMART,
}

_MARKETPLACE_ORDER_PLATFORMS: set[OrderPlatform] = {
    OrderPlatform.AMAZON,
    OrderPlatform.EBAY_MEKONG,
    OrderPlatform.EBAY_USAV,
    OrderPlatform.EBAY_DRAGON,
    OrderPlatform.WALMART,
}

SYNC_BUFFER_MINUTES = 10


def _to_decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except Exception:
        return Decimal("0")


def _normalized_item_total(ext_item: ExternalOrderItem, platform: OrderPlatform) -> Decimal:
    unit_price = _to_decimal(ext_item.unit_price)
    quantity = Decimal(int(getattr(ext_item, "quantity", 0) or 0))
    raw_total = _to_decimal(ext_item.total_price)
    computed_total = unit_price * quantity if quantity > 0 else Decimal("0")

    if platform in _MARKETPLACE_ORDER_PLATFORMS and computed_total > Decimal("0"):
        return computed_total
    if raw_total > Decimal("0"):
        return raw_total
    if computed_total > Decimal("0"):
        return computed_total
    return Decimal("0")


def _normalized_order_amounts(ext: ExternalOrder, platform: OrderPlatform) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    item_subtotal = sum((_normalized_item_total(item, platform) for item in ext.items or []), Decimal("0"))
    raw_subtotal = _to_decimal(ext.subtotal)
    tax_amount = _to_decimal(ext.tax)
    shipping_amount = _to_decimal(ext.shipping)
    raw_total = _to_decimal(ext.total)

    if platform in _MARKETPLACE_ORDER_PLATFORMS:
        subtotal = item_subtotal if item_subtotal > Decimal("0") else raw_subtotal
        handling_candidates = []
        if raw_total > Decimal("0"):
            base_without_tax = raw_total - (subtotal + shipping_amount)
            base_with_tax = raw_total - (subtotal + shipping_amount + tax_amount)
            handling_candidates = [candidate for candidate in (base_with_tax, base_without_tax) if candidate >= Decimal("0")]
        handling_amount = min(handling_candidates) if handling_candidates else Decimal("0")
        total_amount = subtotal + shipping_amount + handling_amount
        return subtotal, tax_amount, shipping_amount, total_amount

    subtotal = raw_subtotal if raw_subtotal > Decimal("0") else item_subtotal
    total_amount = raw_total if raw_total > Decimal("0") else (subtotal + tax_amount + shipping_amount)
    return subtotal, tax_amount, shipping_amount, total_amount


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
        *,
        source: Optional[str] = None,
        fulfillment_channel: Optional[OrderFulfillmentChannel] = None,
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
        logger.debug(f"[DEBUG.INTERNAL_API] {platform_name}: Attempting to acquire sync lock")
        locked = await self.sync_repo.acquire_sync_lock(platform_name)
        logger.debug(f"[DEBUG.INTERNAL_API] {platform_name}: Lock acquired={locked}")
        if not locked:
            state = await self.sync_repo.get_by_platform(platform_name)
            state_error = (state.last_error_message or "").lower() if state else ""
            if state and state.current_status == IntegrationSyncStatus.ERROR and any(
                marker in state_error for marker in _NON_BLOCKING_AUTH_ERROR_MARKERS
            ):
                logger.info(
                    "%s: Auto-resetting prior auth/config error state to retry sync.",
                    platform_name,
                )
                await self.sync_repo.reset_to_idle(platform_name)
                await self.session.flush()
                locked = await self.sync_repo.acquire_sync_lock(platform_name)
                logger.debug(f"[DEBUG.INTERNAL_API] {platform_name}: Lock acquired after auto-reset={locked}")

        if not locked:
            response.success = False
            error_msg = f"Platform '{platform_name}' is currently syncing or in error. Reset the state before retrying."
            logger.warning(f"{platform_name}: {error_msg}")
            response.errors.append(error_msg)
            return response

        try:
            # Step 2 – determine fetch window
            logger.debug(f"[DEBUG.INTERNAL_API] {platform_name}: Retrieving integration state")
            state = await self.sync_repo.get_by_platform(platform_name)
            last_sync = state.last_successful_sync if state else None
            logger.debug(f"[DEBUG.INTERNAL_API] {platform_name}: Last successful sync = {last_sync}")
            if last_sync is None:
                # Never synced – use a sensible default
                fetch_since = datetime(2026, 1, 1, tzinfo=timezone.utc)
                logger.debug(f"[DEBUG.INTERNAL_API] {platform_name}: Never synced before, using default anchor: {fetch_since}")
            else:
                fetch_since = last_sync - timedelta(minutes=SYNC_BUFFER_MINUTES)
                logger.debug(f"[DEBUG.INTERNAL_API] {platform_name}: Using last_sync minus {SYNC_BUFFER_MINUTES}min buffer: {fetch_since}")

            logger.debug(
                "[DEBUG.EXTERNAL_API] %s: Calling client.fetch_orders(since=%s)",
                platform_name,
                fetch_since.isoformat(),
            )

            # Step 3 – call external adapter
            external_orders: list[ExternalOrder] = await client.fetch_orders(
                since=fetch_since,
            )
            logger.debug(
                "[DEBUG.EXTERNAL_API] %s: Adapter returned %d orders",
                platform_name,
                len(external_orders),
            )

            # Step 4 – ingest
            order_platform = _PLATFORM_MAP.get(platform_name)
            logger.debug(f"[DEBUG.INTERNAL_API] {platform_name}: Mapped to order platform enum: {order_platform}")
            if order_platform is None:
                raise ValueError(f"Unknown platform mapping for '{platform_name}'")

            logger.debug(f"[DEBUG.INTERNAL_API] {platform_name}: Starting ingestion of {len(external_orders)} orders")
            for idx, ext_order in enumerate(external_orders, 1):
                logger.debug(f"{platform_name}: Ingesting order {idx}/{len(external_orders)}: {ext_order.platform_order_id}")
                ingest_state = await self._ingest_order(
                    ext_order,
                    order_platform,
                    response,
                    source=source or self._platform_source(platform_name),
                    fulfillment_channel=fulfillment_channel,
                )
                if ingest_state == "unchanged":
                    response.skipped_duplicates += 1
                    logger.debug(f"{platform_name}: Order {ext_order.platform_order_id} was duplicate, skipped")

            # Step 5 – mark success & update anchor
            logger.debug(f"[DEBUG.INTERNAL_API] {platform_name}: Ingestion complete, releasing lock and marking success")
            await self.sync_repo.release_sync_success(platform_name)
            await self.session.commit()
            logger.info(f"{platform_name}: Sync completed successfully")

        except Exception as exc:
            await self.session.rollback()
            error_msg = f"{type(exc).__name__}: {exc}"
            logger.exception("=== Sync %s FAILED ===: %s", platform_name, error_msg)
            logger.error(f"{platform_name}: Exception details:", exc_info=True)
            # Re-acquire a fresh session state for the error update
            logger.debug(f"[DEBUG.INTERNAL_API] {platform_name}: Releasing lock and marking ERROR state")
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
        *,
        source: Optional[str] = None,
        fulfillment_channel: Optional[OrderFulfillmentChannel] = None,
    ) -> SyncResponse:
        """
        Fetch orders within an explicit date range.

        Unlike ``sync_platform``, this does **not** acquire a sync lock or
        update the IntegrationState anchor.  Deduplication still applies:
        orders already in the database are silently skipped.
        """
        logger.debug(
            "[DEBUG.INTERNAL_API] === Admin range sync for %s  [%s → %s] ===",
            platform_name, since.isoformat(), until.isoformat(),
        )
        response = SyncResponse(platform=platform_name)

        try:
            external_orders: list[ExternalOrder] = await client.fetch_orders(
                since=since, until=until,
            )
            logger.debug("[DEBUG.EXTERNAL_API] %s: Adapter returned %d orders", platform_name, len(external_orders))

            order_platform = _PLATFORM_MAP.get(platform_name)
            if order_platform is None:
                raise ValueError(f"Unknown platform mapping for '{platform_name}'")

            for ext_order in external_orders:
                ingest_state = await self._ingest_order(
                    ext_order,
                    order_platform,
                    response,
                    source=source or self._platform_source(platform_name),
                    fulfillment_channel=fulfillment_channel,
                )
                if ingest_state == "unchanged":
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

    @staticmethod
    def _normalize_matching_name(value: str | None) -> str:
        text = (value or "").strip().lower()
        return re.sub(r"[^a-z0-9]+", "", text)

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

    async def refresh_unmatched_item_matches(self) -> dict[str, int]:
        """
        Re-check unmatched sales-order items against PLATFORM_LISTING mappings.

        Matching strategy:
        1) external_item_id -> platform_listing.external_ref_id
        2) exact item_name -> platform_listing.listed_name (case-insensitive)
        """
        unmatched_items = (
            await self.session.execute(
                select(OrderItem).where(OrderItem.status == OrderItemStatus.UNMATCHED)
            )
        ).scalars().all()

        order_cache: dict[int, Optional[Order]] = {}
        listing_name_cache: dict[Platform, dict[str, PlatformListing]] = {}
        checked = 0
        matched = 0

        for item in unmatched_items:
            checked += 1
            if item.order_id not in order_cache:
                order_cache[item.order_id] = await self.order_repo.get(item.order_id)
            order = order_cache[item.order_id]
            if order is None:
                continue

            entity_platform = _ORDER_TO_ENTITY_PLATFORM.get(order.platform)
            if entity_platform is None:
                continue

            listing = None
            ext_ref = str(item.external_item_id or "").strip()
            if ext_ref:
                listing = await self.listing_repo.get_active_by_external_ref(entity_platform, ext_ref)

            if listing is None:
                normalized_item_name = self._normalize_matching_name(item.item_name)
                if normalized_item_name:
                    platform_cache = listing_name_cache.get(entity_platform)
                    if platform_cache is None:
                        platform_cache = {}
                        listings = await self.listing_repo.list_active_with_listed_name(entity_platform)
                        for listing_item in listings:
                            normalized_listing_name = self._normalize_matching_name(listing_item.listed_name)
                            if normalized_listing_name and normalized_listing_name not in platform_cache:
                                platform_cache[normalized_listing_name] = listing_item
                        listing_name_cache[entity_platform] = platform_cache
                    listing = platform_cache.get(normalized_item_name)

            if listing is None or listing.variant_id is None:
                continue

            item.variant_id = listing.variant_id
            item.status = OrderItemStatus.MATCHED
            item.platform_listing_id = listing.id
            self.session.add(item)
            matched += 1

        await self.session.flush()
        return {
            "checked_items": checked,
            "matched_items": matched,
            "unmatched_items": max(checked - matched, 0),
        }

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

    async def _is_tracking_duplicate(self, tracking_number: str, exclude_order_id: Optional[int] = None) -> bool:
        if not tracking_number or not tracking_number.strip():
            return False
        val = tracking_number.strip()
        stmt = select(Order).where(
            func.lower(Order.tracking_number) == func.lower(val)
        )
        if exclude_order_id is not None:
            stmt = stmt.where(Order.id != exclude_order_id)
        duplicate = (await self.session.execute(stmt)).scalars().first()
        return duplicate is not None

    async def _ingest_order(
        self,
        ext: ExternalOrder,
        platform: OrderPlatform,
        response: SyncResponse,
        *,
        source: str,
        fulfillment_channel: Optional[OrderFulfillmentChannel] = None,
    ) -> str:
        """
        Insert or update a single external order + items.

        Returns one of: ``created``, ``updated``, ``unchanged``.
        """
        # Deduplication check
        existing = await self.order_repo.get_by_external_id(
            platform, ext.platform_order_id,
        )
        if existing is not None:
            changed = await self._update_existing_order(
                existing=existing,
                ext=ext,
                platform=platform,
                response=response,
                source=source,
                fulfillment_channel=fulfillment_channel,
            )
            return "updated" if changed else "unchanged"

        # Upsert/lookup Customer (if any data is available)
        customer_id = await self._get_or_create_customer(ext, source=source)

        incoming_subtotal, incoming_tax, incoming_shipping, incoming_total = _normalized_order_amounts(ext, platform)

        tracking = self._extract_tracking_number(ext)
        carrier = self._extract_carrier(ext)
        if tracking and await self._is_tracking_duplicate(tracking):
            logger.warning(
                f"Duplicate tracking number '{tracking}' found for incoming order '{ext.platform_order_id}'. "
                f"Skipping tracking assignment to prevent duplicates."
            )
            tracking = None

        # Build the Order header
        order_data = {
            "platform": platform,
            "source": source,
            "fulfillment_channel": fulfillment_channel or OrderFulfillmentChannel.SELF_FULFILLED,
            "external_order_id": ext.platform_order_id,
            "external_order_number": ext.platform_order_number,
            "status": OrderStatus.PENDING,
            "customer_id": customer_id,
            "subtotal_amount": incoming_subtotal,
            "tax_amount": incoming_tax,
            "shipping_amount": incoming_shipping,
            "total_amount": incoming_total,
            "currency": ext.currency or "USD",
            "ordered_at": ext.ordered_at,
            "tracking_number": tracking,
            "carrier": carrier,
            "platform_data": ext.raw_data,
        }

        try:
            order = await self.order_repo.create(order_data)
        except IntegrityError:
            # Race condition – another request inserted the same order
            await self.session.rollback()
            return "unchanged"

        response.new_orders += 1

        # Insert line items with auto-match
        for ext_item in ext.items:
            await self._ingest_item(ext_item, order, platform, response)

        return "created"

    async def _update_existing_order(
        self,
        *,
        existing: Order,
        ext: ExternalOrder,
        platform: OrderPlatform,
        response: SyncResponse,
        source: str,
        fulfillment_channel: Optional[OrderFulfillmentChannel] = None,
    ) -> bool:
        changed = False

        customer_id = await self._get_or_create_customer(ext, source=source)
        if customer_id is not None and existing.customer_id != customer_id:
            existing.customer_id = customer_id
            changed = True

        if source and existing.source != source:
            existing.source = source
            changed = True

        if (
            fulfillment_channel == OrderFulfillmentChannel.AMAZON_FBA
            and existing.fulfillment_channel != OrderFulfillmentChannel.AMAZON_FBA
        ):
            existing.fulfillment_channel = OrderFulfillmentChannel.AMAZON_FBA
            changed = True

        if ext.platform_order_number and existing.external_order_number != ext.platform_order_number:
            existing.external_order_number = ext.platform_order_number
            changed = True

        incoming_ordered_at = ext.ordered_at
        if incoming_ordered_at is not None and existing.ordered_at != incoming_ordered_at:
            existing.ordered_at = incoming_ordered_at
            changed = True

        incoming_tracking = self._extract_tracking_number(ext)
        if incoming_tracking and existing.tracking_number != incoming_tracking:
            if await self._is_tracking_duplicate(incoming_tracking, exclude_order_id=existing.id):
                logger.warning(
                    f"Duplicate tracking number '{incoming_tracking}' found for existing order '{existing.external_order_id}'. "
                    f"Skipping tracking update to prevent duplicates."
                )
            else:
                existing.tracking_number = incoming_tracking
                changed = True

        incoming_carrier = self._extract_carrier(ext)
        if incoming_carrier and existing.carrier != incoming_carrier:
            existing.carrier = incoming_carrier
            changed = True

        incoming_subtotal, incoming_tax, incoming_shipping, incoming_total = _normalized_order_amounts(ext, platform)
        incoming_currency = ext.currency or "USD"

        if existing.subtotal_amount != incoming_subtotal:
            existing.subtotal_amount = incoming_subtotal
            changed = True
        if existing.tax_amount != incoming_tax:
            existing.tax_amount = incoming_tax
            changed = True
        if existing.shipping_amount != incoming_shipping:
            existing.shipping_amount = incoming_shipping
            changed = True
        if existing.total_amount != incoming_total:
            existing.total_amount = incoming_total
            changed = True
        if existing.currency != incoming_currency:
            existing.currency = incoming_currency
            changed = True
        if existing.platform_data != ext.raw_data:
            existing.platform_data = ext.raw_data
            changed = True

        item_changed = await self._upsert_existing_order_items(
            order=existing,
            ext_items=ext.items,
            platform=platform,
            response=response,
        )
        if item_changed:
            changed = True

        if changed:
            self.session.add(existing)
        return changed

    @staticmethod
    def _item_identity_key(
        external_item_id: Optional[str],
        external_sku: Optional[str],
        item_name: Optional[str],
    ) -> str:
        item_id = str(external_item_id or "").strip().lower()
        if item_id:
            return f"id:{item_id}"
        sku = str(external_sku or "").strip().lower()
        if sku:
            return f"sku:{sku}"
        title = str(item_name or "").strip().lower()
        return f"title:{title}"

    async def _upsert_existing_order_items(
        self,
        *,
        order: Order,
        ext_items: Sequence[ExternalOrderItem],
        platform: OrderPlatform,
        response: SyncResponse,
    ) -> bool:
        existing_items = (
            await self.session.execute(select(OrderItem).where(OrderItem.order_id == order.id))
        ).scalars().all()

        by_key: dict[str, list[OrderItem]] = {}
        for item in existing_items:
            key = self._item_identity_key(item.external_item_id, item.external_sku, item.item_name)
            by_key.setdefault(key, []).append(item)

        changed = False
        for ext_item in ext_items:
            key = self._item_identity_key(ext_item.platform_item_id, ext_item.platform_sku, ext_item.title)
            bucket = by_key.get(key) or []
            if bucket:
                item = bucket.pop(0)
                item_changed = await self._update_existing_item_fields(
                    item=item,
                    ext_item=ext_item,
                    platform=platform,
                    response=response,
                )
                if item_changed:
                    self.session.add(item)
                    changed = True
                continue

            await self._ingest_item(ext_item, order, platform, response)
            changed = True

        return changed

    async def _update_existing_item_fields(
        self,
        *,
        item: OrderItem,
        ext_item: ExternalOrderItem,
        platform: OrderPlatform,
        response: SyncResponse,
    ) -> bool:
        changed = False

        if item.external_item_id != ext_item.platform_item_id:
            item.external_item_id = ext_item.platform_item_id
            changed = True
        if item.external_sku != ext_item.platform_sku:
            item.external_sku = ext_item.platform_sku
            changed = True
        if item.external_asin != ext_item.asin:
            item.external_asin = ext_item.asin
            changed = True
        if item.item_name != ext_item.title:
            item.item_name = ext_item.title
            changed = True
        if item.quantity != ext_item.quantity:
            item.quantity = ext_item.quantity
            changed = True

        incoming_unit = _to_decimal(ext_item.unit_price)
        incoming_total = _normalized_item_total(ext_item, platform)
        if item.unit_price != incoming_unit:
            item.unit_price = incoming_unit
            changed = True
        if item.total_price != incoming_total:
            item.total_price = incoming_total
            changed = True
        if item.item_metadata != ext_item.raw_data:
            item.item_metadata = ext_item.raw_data
            changed = True

        if item.status == OrderItemStatus.UNMATCHED:
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

            if variant_id is None and entity_platform and ext_item.platform_sku:
                listing = await self.listing_repo.get_active_by_external_ref(
                    entity_platform, ext_item.platform_sku,
                )
                if listing is not None:
                    variant_id = listing.variant_id
                    item_status = OrderItemStatus.MATCHED
                    response.auto_matched += 1

            if variant_id is None and entity_platform and ext_item.title:
                listing = await self.listing_repo.search_active_by_listed_name(
                    entity_platform, ext_item.title,
                )
                if listing is not None:
                    variant_id = listing.variant_id
                    item_status = OrderItemStatus.MATCHED
                    response.auto_matched += 1

            if item.variant_id != variant_id:
                item.variant_id = variant_id
                changed = True
            if item.status != item_status:
                item.status = item_status
                changed = True

        return changed

    @staticmethod
    def _platform_source(platform_name: str) -> str:
        return f"{platform_name.upper()}_API"

    @staticmethod
    def _coalesce(value: Optional[str]) -> Optional[str]:
        text = str(value or "").strip()
        return text or None

    def _extract_tracking_number(self, ext: ExternalOrder) -> Optional[str]:
        direct = self._coalesce(getattr(ext, "tracking_number", None))
        if direct:
            return direct
        raw = getattr(ext, "raw_data", None) or {}
        if not isinstance(raw, dict):
            return None
        return (
            self._coalesce(raw.get("trackingNumber"))
            or self._coalesce(raw.get("tracking_number"))
            or self._coalesce(raw.get("Tracking Number"))
            or self._coalesce(raw.get("tracking"))
        )

    def _extract_carrier(self, ext: ExternalOrder) -> Optional[str]:
        direct = self._coalesce(getattr(ext, "carrier", None))
        if direct:
            return direct
        raw = getattr(ext, "raw_data", None) or {}
        if not isinstance(raw, dict):
            return None
        return (
            self._coalesce(raw.get("carrier"))
            or self._coalesce(raw.get("Carrier"))
            or self._coalesce(raw.get("shipping_carrier"))
        )

    def _merge_customer_fields(self, customer: Customer, ext: ExternalOrder, source: Optional[str]) -> bool:
        changed = False

        incoming_name = self._coalesce(ext.customer_name)
        incoming_email = self._coalesce(ext.customer_email)
        incoming_external_id = self._coalesce(getattr(ext, "customer_external_id", None))
        incoming_phone = self._coalesce(ext.customer_phone)
        incoming_company = self._coalesce(ext.customer_company)
        incoming_source = self._coalesce(ext.customer_source) or self._coalesce(source)

        if incoming_name and (not self._coalesce(customer.name) or customer.name == "Unknown"):
            customer.name = incoming_name
            changed = True
        if incoming_email and not self._coalesce(customer.email):
            customer.email = incoming_email
            changed = True
        if incoming_phone and not self._coalesce(customer.phone):
            customer.phone = incoming_phone
            changed = True
        if incoming_company and not self._coalesce(customer.company_name):
            customer.company_name = incoming_company
            changed = True
        if incoming_external_id and not self._coalesce(customer.amazon_buyer_id):
            customer.amazon_buyer_id = incoming_external_id
            changed = True

        if ext.ship_address_line1 and not self._coalesce(customer.address_line1):
            customer.address_line1 = ext.ship_address_line1
            changed = True
        if ext.ship_address_line2 and not self._coalesce(customer.address_line2):
            customer.address_line2 = ext.ship_address_line2
            changed = True
        if ext.ship_address_line3 and not self._coalesce(customer.address_line2):
            customer.address_line2 = ext.ship_address_line3
            changed = True
        if ext.ship_city and not self._coalesce(customer.city):
            customer.city = ext.ship_city
            changed = True
        if ext.ship_state and not self._coalesce(customer.state):
            customer.state = ext.ship_state
            changed = True
        if ext.ship_postal_code and not self._coalesce(customer.postal_code):
            customer.postal_code = ext.ship_postal_code
            changed = True
        if ext.ship_country and not self._coalesce(customer.country):
            customer.country = ext.ship_country
            changed = True

        # Keep latest known source; this is intentionally overwrite-oriented.
        if incoming_source and incoming_source != customer.source:
            customer.source = incoming_source
            changed = True

        return changed

    async def _get_or_create_customer(self, ext: ExternalOrder, *, source: Optional[str]) -> Optional[int]:
        """Find or create a Customer from external order details."""
        if not (ext.customer_name or ext.customer_email or ext.customer_phone):
            return None

        if ext.customer_external_id:
            existing = await self.session.execute(
                select(Customer).where(Customer.amazon_buyer_id == ext.customer_external_id)
            )
            customer = existing.scalar_one_or_none()
            if customer:
                if self._merge_customer_fields(customer, ext, source):
                    self.session.add(customer)
                return customer.id

        # Prefer email for deterministic matching
        if ext.customer_email:
            existing = await self.session.execute(
                select(Customer).where(Customer.email == ext.customer_email)
            )
            customer = existing.scalar_one_or_none()
            if customer:
                if self._merge_customer_fields(customer, ext, source):
                    self.session.add(customer)
                return customer.id

        # Fallback: match by name + postal code if available
        if ext.customer_name:
            query = select(Customer).where(Customer.name == ext.customer_name)
            if ext.ship_postal_code:
                query = query.where(Customer.postal_code == ext.ship_postal_code)
            existing = await self.session.execute(query)
            customer = existing.scalar_one_or_none()
            if customer:
                if self._merge_customer_fields(customer, ext, source):
                    self.session.add(customer)
                return customer.id

        # Create new customer
        customer = Customer(
            name=ext.customer_name or "Unknown",
            email=ext.customer_email,
            amazon_buyer_id=self._coalesce(getattr(ext, "customer_external_id", None)),
            phone=ext.customer_phone,
            company_name=ext.customer_company,
            address_line1=ext.ship_address_line1,
            address_line2=ext.ship_address_line2 or ext.ship_address_line3,
            city=ext.ship_city,
            state=ext.ship_state,
            postal_code=ext.ship_postal_code,
            country=ext.ship_country or "US",
            source=self._coalesce(ext.customer_source) or self._coalesce(source),
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
            logger.debug(
                "[DEBUG.INTERNAL_API] Auto-match fallback item='%s' platform_item_id=%s platform_sku=%s platform=%s",
                ext_item.title,
                ext_item.platform_item_id,
                ext_item.platform_sku,
                platform,
            )
            listing = await self.listing_repo.search_active_by_listed_name(
                entity_platform, ext_item.title,
            )
            if listing is not None:
                variant_id = listing.variant_id
                item_status = OrderItemStatus.MATCHED
                response.auto_matched += 1
                logger.debug(
                    "[DEBUG.INTERNAL_API] Name-matched item '%s' → variant %d via listing '%s'",
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
            "unit_price": _to_decimal(ext_item.unit_price),
            "total_price": _normalized_item_total(ext_item, platform),
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

        logger.debug(
            "[DEBUG.INTERNAL_API] Learn listing candidate order_item_id=%s platform=%s variant_id=%s external_ref=%s item_name=%s",
            item.id,
            order.platform,
            variant_id,
            ext_ref,
            item.item_name,
        )

        # If this external ref already exists, prefer updating that listing
        # (but block creating a new mapping that points the same ext_ref to
        # a different variant). This allows a single variant to have multiple
        # listings on the same platform as long as each listing uses a unique
        # external_ref_id.
        if ext_ref:
            ref_existing = await self.listing_repo.get_by_external_ref(
                entity_platform, ext_ref,
            )
            if ref_existing is not None:
                logger.debug(
                    "[DEBUG.INTERNAL_API] Existing listing found for external_ref=%s platform=%s listing_id=%s variant_id=%s target_variant_id=%s",
                    ext_ref,
                    entity_platform,
                    ref_existing.id,
                    ref_existing.variant_id,
                    variant_id,
                )
                # If the existing listing maps to a different variant, do not
                # create a conflicting mapping.
                if ref_existing.variant_id != variant_id:
                    logger.debug(
                        "[DEBUG.INTERNAL_API] Skipping learn_listing because external_ref=%s is already bound to variant_id=%s",
                        ext_ref,
                        ref_existing.variant_id,
                    )
                    return

                # Same variant: enrich missing fields and finish.
                changed = False
                if not ref_existing.external_ref_id and ext_ref:
                    ref_existing.external_ref_id = ext_ref
                    changed = True
                if not ref_existing.listed_name and item.item_name:
                    ref_existing.listed_name = item.item_name
                    changed = True
                if not ref_existing.listing_price and item.unit_price:
                    ref_existing.listing_price = item.unit_price
                    changed = True
                if changed:
                    self.session.add(ref_existing)
                    try:
                        await self.session.flush()
                    except IntegrityError:
                        await self.session.rollback()
                logger.debug(
                    "[DEBUG.INTERNAL_API] Reused existing listing for external_ref=%s platform=%s listing_id=%s",
                    ext_ref,
                    entity_platform,
                    ref_existing.id,
                )
                return

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
            logger.debug(
                "[DEBUG.INTERNAL_API] Created learned listing external_ref=%s platform=%s variant_id=%s listing_id=%s",
                ext_ref,
                entity_platform,
                variant_id,
                listing.id,
            )
        except IntegrityError:
            # Another concurrent request already created this listing
            await self.session.rollback()
