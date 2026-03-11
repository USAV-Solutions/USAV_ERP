"""Purchasing service logic."""
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import InventoryStatus, PurchaseDeliverStatus, PurchaseOrderItemStatus
from app.models.entities import InventoryItem
from app.models.entities import ProductVariant
from app.modules.purchasing.schemas import ItemReceipt
from app.repositories.inventory import InventoryItemRepository
from app.repositories.purchasing import PurchaseOrderItemRepository, PurchaseOrderRepository


class PurchasingService:
    """Business logic for PO item matching and receiving."""

    def __init__(
        self,
        session: AsyncSession,
        po_repo: PurchaseOrderRepository,
        po_item_repo: PurchaseOrderItemRepository,
        inventory_repo: InventoryItemRepository,
    ):
        self.session = session
        self.po_repo = po_repo
        self.po_item_repo = po_item_repo
        self.inventory_repo = inventory_repo

    async def match_purchase_item(self, item_id: int, variant_id: int):
        """Manually match a PO item to a ProductVariant."""
        item = await self.po_item_repo.get(item_id)
        if item is None:
            raise ValueError(f"PurchaseOrderItem {item_id} not found")

        variant = await self.session.get(ProductVariant, variant_id)
        if variant is None:
            raise ValueError(f"ProductVariant {variant_id} not found")

        item.variant_id = variant_id
        # Keep PO line text aligned with the matched internal catalog item.
        item.external_item_name = variant.variant_name or variant.full_sku
        item.status = PurchaseOrderItemStatus.MATCHED
        self.session.add(item)
        await self.session.flush()
        await self.session.refresh(item)
        return item

    async def receive_purchase_order(self, po_id: int, received_items: list[ItemReceipt]) -> list[InventoryItem]:
        """
        Mark a purchase order as delivered and create unit-level inventory rows.

        One InventoryItem row is created per received unit so serial-based stock
        constraints remain intact.
        """
        po = await self.po_repo.get_with_items_and_vendor(po_id)
        if po is None:
            raise ValueError(f"PurchaseOrder {po_id} not found")

        if po.deliver_status == PurchaseDeliverStatus.DELIVERED:
            raise ValueError(f"PurchaseOrder {po_id} is already delivered")

        item_map = {item.id: item for item in po.items}
        created_inventory_rows: list[InventoryItem] = []

        for receipt in received_items:
            po_item = item_map.get(receipt.purchase_order_item_id)
            if po_item is None:
                raise ValueError(
                    f"PurchaseOrderItem {receipt.purchase_order_item_id} not found on PO {po_id}"
                )
            if po_item.variant_id is None:
                raise ValueError(
                    f"PurchaseOrderItem {po_item.id} is unmatched. Match to a variant first."
                )

            serials = [s.strip() for s in receipt.serial_numbers if s and s.strip()]
            if serials and len(serials) != receipt.quantity_received:
                raise ValueError(
                    f"Item {po_item.id}: serial_numbers count must equal quantity_received when provided"
                )

            for idx in range(receipt.quantity_received):
                serial_number = (
                    serials[idx]
                    if serials
                    else f"PO{po.id}-{po_item.variant_id}-{idx + 1}"
                )
                # Ensure generated serials do not conflict with existing rows.
                existing = await self.inventory_repo.get_by_serial(serial_number)
                if existing is not None:
                    serial_number = f"{serial_number}-{int(datetime.now(tz=timezone.utc).timestamp())}"

                inv = InventoryItem(
                    serial_number=serial_number,
                    variant_id=po_item.variant_id,
                    status=InventoryStatus.AVAILABLE,
                    location_code=receipt.location_code,
                    cost_basis=po_item.unit_price,
                    notes=f"Received from PO {po.po_number}",
                    received_at=datetime.now(tz=timezone.utc),
                )
                self.session.add(inv)
                created_inventory_rows.append(inv)

            po_item.status = PurchaseOrderItemStatus.RECEIVED
            self.session.add(po_item)

        po.deliver_status = PurchaseDeliverStatus.DELIVERED
        self.session.add(po)

        await self.session.flush()
        for row in created_inventory_rows:
            await self.session.refresh(row)

        return created_inventory_rows
