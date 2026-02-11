"""
Order Sync Service – unit tests.

Tests the OrderSyncService with fully mocked repositories and platform
clients so we can validate:
  - Safe Sync lifecycle (lock → fetch → ingest → release)
  - Deduplication (skip existing orders)
  - Auto-match via PLATFORM_LISTING
  - Manual Match & Learn
  - Confirm / Reject workflows
"""
import pytest
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Sequence
from unittest.mock import AsyncMock, MagicMock, patch

from app.integrations.base import ExternalOrder, ExternalOrderItem, BasePlatformClient
from app.models.entities import Platform, PlatformListing
from app.modules.orders.models import (
    IntegrationState,
    IntegrationSyncStatus,
    Order,
    OrderItem,
    OrderItemStatus,
    OrderPlatform,
    OrderStatus,
)
from app.modules.orders.service import OrderSyncService


# ==========================================================================
#  Helpers
# ==========================================================================

def _make_external_order(
    order_id: str = "EXT-001",
    items: list[ExternalOrderItem] | None = None,
) -> ExternalOrder:
    """Build a minimal ExternalOrder for testing."""
    if items is None:
        items = [
            ExternalOrderItem(
                platform_item_id="ITEM-A",
                platform_sku="SKU-A",
                asin=None,
                title="Widget A",
                quantity=1,
                unit_price=10.0,
                total_price=10.0,
            )
        ]
    return ExternalOrder(
        platform_order_id=order_id,
        platform_order_number=f"ORD-{order_id}",
        customer_name="Test Customer",
        customer_email="test@example.com",
        ship_address_line1="1 Test Ln",
        ship_address_line2=None,
        ship_city="Testville",
        ship_state="TS",
        ship_postal_code="00000",
        ship_country="US",
        subtotal=10.0,
        tax=1.0,
        shipping=5.0,
        total=16.0,
        currency="USD",
        ordered_at=datetime(2026, 1, 15, tzinfo=timezone.utc),
        items=items,
    )


def _make_order_item(
    item_id: int = 1,
    order_id: int = 100,
    status: OrderItemStatus = OrderItemStatus.UNMATCHED,
    variant_id: int | None = None,
    external_item_id: str | None = "ITEM-A",
    external_sku: str | None = "SKU-A",
) -> OrderItem:
    """Build a mock OrderItem ORM object."""
    item = MagicMock(spec=OrderItem)
    item.id = item_id
    item.order_id = order_id
    item.status = status
    item.variant_id = variant_id
    item.external_item_id = external_item_id
    item.external_sku = external_sku
    item.item_name = "Widget A"
    item.matching_notes = None
    return item


def _make_order(
    order_id: int = 100,
    platform: OrderPlatform = OrderPlatform.ECWID,
    external_order_id: str = "EXT-001",
) -> Order:
    """Build a mock Order ORM object."""
    order = MagicMock(spec=Order)
    order.id = order_id
    order.platform = platform
    order.external_order_id = external_order_id
    return order


def _make_session() -> AsyncMock:
    """Create a mock AsyncSession where sync methods (add) are plain MagicMocks."""
    session = AsyncMock()
    # session.add() is synchronous on SQLAlchemy AsyncSession, so use MagicMock
    # to avoid "coroutine was never awaited" warnings.
    session.add = MagicMock()
    return session


def _make_service(
    session=None,
    sync_repo=None,
    order_repo=None,
    order_item_repo=None,
    listing_repo=None,
) -> OrderSyncService:
    """Create an OrderSyncService with mocked dependencies."""
    return OrderSyncService(
        session=session or _make_session(),
        sync_repo=sync_repo or AsyncMock(),
        order_repo=order_repo or AsyncMock(),
        order_item_repo=order_item_repo or AsyncMock(),
        listing_repo=listing_repo or AsyncMock(),
    )


# ==========================================================================
#  Safe Sync Tests
# ==========================================================================

class TestSyncPlatform:
    """Tests for sync_platform (the Safe Sync engine)."""

    @pytest.mark.asyncio
    async def test_lock_not_acquired_returns_failure(self):
        """If another sync is running (lock fails), return error."""
        sync_repo = AsyncMock()
        sync_repo.acquire_sync_lock.return_value = False

        svc = _make_service(sync_repo=sync_repo)
        client = AsyncMock(spec=BasePlatformClient)

        result = await svc.sync_platform("ECWID", client)

        assert result.success is False
        assert len(result.errors) == 1
        assert "currently syncing" in result.errors[0].lower()
        client.fetch_orders.assert_not_called()

    @pytest.mark.asyncio
    async def test_successful_sync_ingests_orders(self):
        """Happy path: lock → fetch → ingest → release."""
        sync_repo = AsyncMock()
        sync_repo.acquire_sync_lock.return_value = True
        state = MagicMock()
        state.last_successful_sync = datetime(2026, 1, 10, tzinfo=timezone.utc)
        sync_repo.get_by_platform.return_value = state

        order_repo = AsyncMock()
        order_repo.get_by_external_id.return_value = None  # not a duplicate
        created_order = _make_order()
        order_repo.create.return_value = created_order

        listing_repo = AsyncMock()
        listing_repo.get_by_external_ref.return_value = None  # no auto-match

        order_item_repo = AsyncMock()

        svc = _make_service(
            sync_repo=sync_repo,
            order_repo=order_repo,
            order_item_repo=order_item_repo,
            listing_repo=listing_repo,
        )

        client = AsyncMock(spec=BasePlatformClient)
        client.fetch_orders.return_value = [_make_external_order()]

        result = await svc.sync_platform("ECWID", client)

        assert result.success is True
        assert result.new_orders == 1
        assert result.new_items == 1
        assert result.skipped_duplicates == 0
        sync_repo.release_sync_success.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_duplicate_order_skipped(self):
        """If order already exists, skip it and increment skipped_duplicates."""
        sync_repo = AsyncMock()
        sync_repo.acquire_sync_lock.return_value = True
        state = MagicMock()
        state.last_successful_sync = datetime(2026, 1, 10, tzinfo=timezone.utc)
        sync_repo.get_by_platform.return_value = state

        order_repo = AsyncMock()
        order_repo.get_by_external_id.return_value = _make_order()  # already exists

        svc = _make_service(sync_repo=sync_repo, order_repo=order_repo)

        client = AsyncMock(spec=BasePlatformClient)
        client.fetch_orders.return_value = [_make_external_order()]

        result = await svc.sync_platform("ECWID", client)

        assert result.success is True
        assert result.new_orders == 0
        assert result.skipped_duplicates == 1
        order_repo.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_adapter_exception_captured(self):
        """If the platform adapter throws, error is captured gracefully."""
        sync_repo = AsyncMock()
        sync_repo.acquire_sync_lock.return_value = True
        state = MagicMock()
        state.last_successful_sync = None
        sync_repo.get_by_platform.return_value = state

        session = _make_session()
        svc = _make_service(session=session, sync_repo=sync_repo)

        client = AsyncMock(spec=BasePlatformClient)
        client.fetch_orders.side_effect = RuntimeError("API timeout")

        result = await svc.sync_platform("ECWID", client)

        assert result.success is False
        assert any("API timeout" in e for e in result.errors)
        sync_repo.release_sync_error.assert_awaited_once()
        session.rollback.assert_awaited()

    @pytest.mark.asyncio
    async def test_never_synced_uses_default_anchor(self):
        """If last_successful_sync is None, fetch window starts at default."""
        sync_repo = AsyncMock()
        sync_repo.acquire_sync_lock.return_value = True
        state = MagicMock()
        state.last_successful_sync = None
        sync_repo.get_by_platform.return_value = state

        order_repo = AsyncMock()
        listing_repo = AsyncMock()
        listing_repo.get_by_external_ref.return_value = None

        svc = _make_service(
            sync_repo=sync_repo,
            order_repo=order_repo,
            listing_repo=listing_repo,
        )

        client = AsyncMock(spec=BasePlatformClient)
        client.fetch_orders.return_value = []

        result = await svc.sync_platform("ECWID", client)

        assert result.success is True
        # Verify fetch_orders was called (even if no orders returned)
        client.fetch_orders.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_multiple_orders_ingested(self):
        """Correctly process a batch of multiple orders."""
        sync_repo = AsyncMock()
        sync_repo.acquire_sync_lock.return_value = True
        state = MagicMock()
        state.last_successful_sync = datetime(2026, 1, 10, tzinfo=timezone.utc)
        sync_repo.get_by_platform.return_value = state

        order_repo = AsyncMock()
        order_repo.get_by_external_id.return_value = None
        order_repo.create.return_value = _make_order()

        listing_repo = AsyncMock()
        listing_repo.get_by_external_ref.return_value = None

        order_item_repo = AsyncMock()

        svc = _make_service(
            sync_repo=sync_repo,
            order_repo=order_repo,
            order_item_repo=order_item_repo,
            listing_repo=listing_repo,
        )

        ext_orders = [
            _make_external_order("EXT-001"),
            _make_external_order("EXT-002"),
            _make_external_order("EXT-003"),
        ]

        client = AsyncMock(spec=BasePlatformClient)
        client.fetch_orders.return_value = ext_orders

        result = await svc.sync_platform("ECWID", client)

        assert result.success is True
        assert result.new_orders == 3
        assert result.new_items == 3  # each has 1 item


# ==========================================================================
#  Auto-Match Tests
# ==========================================================================

class TestAutoMatch:
    """Tests for the auto-match logic in _ingest_item."""

    @pytest.mark.asyncio
    async def test_auto_match_by_item_id(self):
        """If PLATFORM_LISTING matches external_item_id, item is MATCHED."""
        sync_repo = AsyncMock()
        sync_repo.acquire_sync_lock.return_value = True
        state = MagicMock()
        state.last_successful_sync = datetime(2026, 1, 10, tzinfo=timezone.utc)
        sync_repo.get_by_platform.return_value = state

        order_repo = AsyncMock()
        order_repo.get_by_external_id.return_value = None
        created_order = _make_order()
        order_repo.create.return_value = created_order

        # Listing repo returns a match for the external item id
        listing = MagicMock(spec=PlatformListing)
        listing.variant_id = 42
        listing_repo = AsyncMock()
        listing_repo.get_by_external_ref.return_value = listing

        order_item_repo = AsyncMock()

        svc = _make_service(
            sync_repo=sync_repo,
            order_repo=order_repo,
            order_item_repo=order_item_repo,
            listing_repo=listing_repo,
        )

        client = AsyncMock(spec=BasePlatformClient)
        client.fetch_orders.return_value = [_make_external_order()]

        result = await svc.sync_platform("ECWID", client)

        assert result.auto_matched == 1
        # Verify the item was created with variant_id and MATCHED status
        call_args = order_item_repo.create.call_args[0][0]
        assert call_args["variant_id"] == 42
        assert call_args["status"] == OrderItemStatus.MATCHED

    @pytest.mark.asyncio
    async def test_auto_match_fallback_to_sku(self):
        """If no match by item_id, fallback to platform_sku lookup."""
        sync_repo = AsyncMock()
        sync_repo.acquire_sync_lock.return_value = True
        state = MagicMock()
        state.last_successful_sync = datetime(2026, 1, 10, tzinfo=timezone.utc)
        sync_repo.get_by_platform.return_value = state

        order_repo = AsyncMock()
        order_repo.get_by_external_id.return_value = None
        order_repo.create.return_value = _make_order()

        # First call (item_id) returns None, second call (sku) returns a match
        listing = MagicMock(spec=PlatformListing)
        listing.variant_id = 99
        listing_repo = AsyncMock()
        listing_repo.get_by_external_ref.side_effect = [None, listing]

        order_item_repo = AsyncMock()

        svc = _make_service(
            sync_repo=sync_repo,
            order_repo=order_repo,
            order_item_repo=order_item_repo,
            listing_repo=listing_repo,
        )

        client = AsyncMock(spec=BasePlatformClient)
        client.fetch_orders.return_value = [_make_external_order()]

        result = await svc.sync_platform("ECWID", client)

        assert result.auto_matched == 1
        call_args = order_item_repo.create.call_args[0][0]
        assert call_args["variant_id"] == 99

    @pytest.mark.asyncio
    async def test_no_match_stays_unmatched(self):
        """If no PLATFORM_LISTING hit, item status stays UNMATCHED."""
        sync_repo = AsyncMock()
        sync_repo.acquire_sync_lock.return_value = True
        state = MagicMock()
        state.last_successful_sync = datetime(2026, 1, 10, tzinfo=timezone.utc)
        sync_repo.get_by_platform.return_value = state

        order_repo = AsyncMock()
        order_repo.get_by_external_id.return_value = None
        order_repo.create.return_value = _make_order()

        listing_repo = AsyncMock()
        listing_repo.get_by_external_ref.return_value = None

        order_item_repo = AsyncMock()

        svc = _make_service(
            sync_repo=sync_repo,
            order_repo=order_repo,
            order_item_repo=order_item_repo,
            listing_repo=listing_repo,
        )

        client = AsyncMock(spec=BasePlatformClient)
        client.fetch_orders.return_value = [_make_external_order()]

        result = await svc.sync_platform("ECWID", client)

        assert result.auto_matched == 0
        call_args = order_item_repo.create.call_args[0][0]
        assert call_args["variant_id"] is None
        assert call_args["status"] == OrderItemStatus.UNMATCHED


# ==========================================================================
#  Manual Match & Learn Tests
# ==========================================================================

class TestManualMatch:
    """Tests for match_item, confirm_item, reject_item."""

    @pytest.mark.asyncio
    async def test_match_item_sets_variant(self):
        """match_item should set variant_id and status=MATCHED."""
        item = _make_order_item()
        order_item_repo = AsyncMock()
        order_item_repo.get.return_value = item

        listing_repo = AsyncMock()
        listing_repo.get_by_external_ref.return_value = None  # not yet learned

        order = _make_order()
        order_repo = AsyncMock()
        order_repo.get.return_value = order

        session = _make_session()
        svc = _make_service(
            session=session,
            order_repo=order_repo,
            order_item_repo=order_item_repo,
            listing_repo=listing_repo,
        )

        result = await svc.match_item(1, variant_id=42, learn=True, notes="Manual fix")

        assert item.variant_id == 42
        assert item.status == OrderItemStatus.MATCHED
        assert item.matching_notes == "Manual fix"
        session.flush.assert_awaited()

    @pytest.mark.asyncio
    async def test_match_item_not_found_raises(self):
        """match_item should raise ValueError if item doesn't exist."""
        order_item_repo = AsyncMock()
        order_item_repo.get.return_value = None

        svc = _make_service(order_item_repo=order_item_repo)

        with pytest.raises(ValueError, match="not found"):
            await svc.match_item(999, variant_id=42)

    @pytest.mark.asyncio
    async def test_match_with_learn_creates_listing(self):
        """When learn=True, a PlatformListing should be created."""
        item = _make_order_item(external_item_id="ITEM-A")
        order_item_repo = AsyncMock()
        order_item_repo.get.return_value = item

        listing_repo = AsyncMock()
        listing_repo.get_by_external_ref.return_value = None

        order = _make_order(platform=OrderPlatform.ECWID)
        order_repo = AsyncMock()
        order_repo.get.return_value = order

        session = _make_session()
        svc = _make_service(
            session=session,
            order_repo=order_repo,
            order_item_repo=order_item_repo,
            listing_repo=listing_repo,
        )

        await svc.match_item(1, variant_id=42, learn=True)

        # Verify session.add was called with a PlatformListing
        add_calls = session.add.call_args_list
        listing_added = any(
            isinstance(c.args[0], PlatformListing)
            for c in add_calls
            if c.args
        )
        assert listing_added, "Expected PlatformListing to be added to session"

    @pytest.mark.asyncio
    async def test_match_without_learn_skips_listing(self):
        """When learn=False, no PlatformListing is created."""
        item = _make_order_item(external_item_id="ITEM-B")
        order_item_repo = AsyncMock()
        order_item_repo.get.return_value = item

        listing_repo = AsyncMock()
        order_repo = AsyncMock()

        session = _make_session()
        svc = _make_service(
            session=session,
            order_repo=order_repo,
            order_item_repo=order_item_repo,
            listing_repo=listing_repo,
        )

        await svc.match_item(1, variant_id=42, learn=False)

        # order_repo.get should NOT have been called (learn path skipped)
        order_repo.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_confirm_item_success(self):
        """confirm_item should succeed on a MATCHED item."""
        item = _make_order_item(status=OrderItemStatus.MATCHED, variant_id=42)
        order_item_repo = AsyncMock()
        order_item_repo.get.return_value = item

        session = _make_session()
        svc = _make_service(session=session, order_item_repo=order_item_repo)

        result = await svc.confirm_item(1, notes="Looks correct")

        assert item.matching_notes == "Looks correct"
        session.flush.assert_awaited()

    @pytest.mark.asyncio
    async def test_confirm_item_wrong_status_raises(self):
        """confirm_item should raise if item is not MATCHED."""
        item = _make_order_item(status=OrderItemStatus.UNMATCHED)
        order_item_repo = AsyncMock()
        order_item_repo.get.return_value = item

        svc = _make_service(order_item_repo=order_item_repo)

        with pytest.raises(ValueError, match="expected MATCHED"):
            await svc.confirm_item(1)

    @pytest.mark.asyncio
    async def test_confirm_item_not_found_raises(self):
        """confirm_item should raise ValueError if item doesn't exist."""
        order_item_repo = AsyncMock()
        order_item_repo.get.return_value = None

        svc = _make_service(order_item_repo=order_item_repo)

        with pytest.raises(ValueError, match="not found"):
            await svc.confirm_item(999)

    @pytest.mark.asyncio
    async def test_reject_item_resets_to_unmatched(self):
        """reject_item should clear variant_id and set UNMATCHED."""
        item = _make_order_item(status=OrderItemStatus.MATCHED, variant_id=42)
        order_item_repo = AsyncMock()
        order_item_repo.get.return_value = item

        session = _make_session()
        svc = _make_service(session=session, order_item_repo=order_item_repo)

        await svc.reject_item(1, notes="Wrong product")

        assert item.variant_id is None
        assert item.status == OrderItemStatus.UNMATCHED
        assert item.matching_notes == "Wrong product"
        session.flush.assert_awaited()

    @pytest.mark.asyncio
    async def test_reject_item_not_found_raises(self):
        """reject_item should raise ValueError if item doesn't exist."""
        order_item_repo = AsyncMock()
        order_item_repo.get.return_value = None

        svc = _make_service(order_item_repo=order_item_repo)

        with pytest.raises(ValueError, match="not found"):
            await svc.reject_item(999)

    @pytest.mark.asyncio
    async def test_reject_default_notes(self):
        """reject_item without explicit notes sets a default message."""
        item = _make_order_item(status=OrderItemStatus.MATCHED, variant_id=42)
        order_item_repo = AsyncMock()
        order_item_repo.get.return_value = item

        session = _make_session()
        svc = _make_service(session=session, order_item_repo=order_item_repo)

        await svc.reject_item(1)

        assert "rejected" in item.matching_notes.lower()
