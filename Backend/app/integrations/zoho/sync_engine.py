"""
Zoho two-way sync engine.

Provides:
* **Outbound** – SQLAlchemy event listeners on ``ProductVariant`` and
  ``Customer`` that enqueue background tasks whenever a record is created
  or updated (unless the change originated from an inbound webhook).
* **Inbound** – Functions consumed by the webhook dispatcher to apply
  Zoho-side changes to the local database (with echo-loop prevention).
* **Mappers** – Convert local models to/from Zoho API payloads.

The "queue" is currently ``asyncio.create_task`` which runs in-process
(sufficient for single-instance deployments).  Swapping to Redis/ARQ later
requires only changing ``_enqueue_*`` helpers.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import event

from app.core.config import settings
from app.core.database import async_session_factory
from app.integrations.zoho.client import ZohoClient, RateLimitError
from app.integrations.zoho.security import generate_payload_hash
from app.models.entities import Customer, ProductVariant, ZohoSyncStatus
from app.models.purchasing import PurchaseOrder, PurchaseOrderItem, Vendor
from app.modules.orders.models import Order, OrderItem

logger = logging.getLogger(__name__)

UNMATCHED_PLACEHOLDER_ITEM_NAME = "unmatched item"
UNMATCHED_PLACEHOLDER_ITEM_SKU = "00000"


# =========================================================================
# PAYLOAD MAPPERS  (USAV → Zoho)
# =========================================================================

def variant_to_zoho_payload(variant: ProductVariant) -> dict[str, Any]:
    """Build the Zoho item payload from a *fully‑loaded* ProductVariant."""
    identity = getattr(variant, "identity", None)
    family = identity.family if identity else None

    payload: dict[str, Any] = {
        "name": variant.variant_name or (family.base_name if family else variant.full_sku),
        "sku": variant.full_sku,
        "description": family.description if family else "",
    }

    # Price – take the first available listing price.
    # Some call sites (or legacy code) may accidentally attach a single
    # PlatformListing instance instead of a list; normalize to an iterable
    # to avoid TypeError: 'PlatformListing' object is not iterable.
    listings_attr = getattr(variant, "listings", None) or []
    listings = (
        listings_attr
        if isinstance(listings_attr, (list, tuple))
        else [listings_attr]
    )

    listing_prices = [
        float(listing.listing_price)
        for listing in listings
        if listing and listing.listing_price is not None
    ]
    if listing_prices:
        payload["rate"] = listing_prices[0]

    if identity:
        if identity.weight is not None:
            payload["weight"] = float(identity.weight)
        if identity.dimension_length is not None:
            payload["length"] = float(identity.dimension_length)
        if identity.dimension_width is not None:
            payload["width"] = float(identity.dimension_width)
        if identity.dimension_height is not None:
            payload["height"] = float(identity.dimension_height)

    return {k: v for k, v in payload.items() if v is not None}


def customer_to_zoho_payload(customer: Customer) -> dict[str, Any]:
    """Build a Zoho *contact* payload from a local ``Customer``."""
    payload: dict[str, Any] = {
        "contact_name": customer.name,
        "contact_type": "customer",
    }
    if customer.email:
        payload["email"] = customer.email
    if customer.phone:
        payload["phone"] = customer.phone
    if customer.company_name:
        payload["company_name"] = customer.company_name

    # Billing address
    address: dict[str, str] = {}
    if customer.address_line1:
        address["address"] = customer.address_line1
    if customer.address_line2:
        address["street2"] = customer.address_line2
    if customer.city:
        address["city"] = customer.city
    if customer.state:
        address["state"] = customer.state
    if customer.postal_code:
        address["zip"] = customer.postal_code
    if customer.country:
        address["country"] = customer.country
    if address:
        payload["billing_address"] = address

    return payload


def vendor_to_zoho_payload(vendor: Vendor) -> dict[str, Any]:
    """Build a Zoho contact payload from a local ``Vendor``."""
    payload: dict[str, Any] = {
        "contact_name": vendor.name,
        "contact_type": "vendor",
    }
    if vendor.email:
        payload["email"] = vendor.email
    if vendor.phone:
        payload["phone"] = vendor.phone
    if vendor.address:
        payload["billing_address"] = {"address": vendor.address}
    return payload


def purchase_order_to_zoho_payload(
    po: PurchaseOrder,
    *,
    unmatched_item_id: Optional[str] = None,
) -> dict[str, Any]:
    """Build a Zoho purchase-order payload from a local ``PurchaseOrder``."""
    vendor = getattr(po, "vendor", None)
    if not (vendor and vendor.zoho_id):
        raise ValueError("PurchaseOrder is missing vendor.zoho_id; sync vendor first.")

    notes_parts: list[str] = []
    if po.notes:
        notes_parts.append(str(po.notes).strip())
    if getattr(po, "source", None):
        notes_parts.append(f"Source: {po.source}")
    if getattr(po, "tracking_number", None):
        notes_parts.append(f"Tracking: {po.tracking_number}")

    payload: dict[str, Any] = {
        "purchaseorder_number": po.po_number,
        "date": po.order_date.strftime("%Y-%m-%d"),
        "vendor_id": vendor.zoho_id,
        "currency_code": po.currency,
        "notes": "\n".join(p for p in notes_parts if p),
    }
    if getattr(po, "tracking_number", None):
        payload["reference_number"] = po.tracking_number
    if po.expected_delivery_date:
        payload["delivery_date"] = po.expected_delivery_date.strftime("%Y-%m-%d")

    def _to_float(value: Any) -> float:
        try:
            return float(value or 0)
        except Exception:
            return 0.0

    tax_amount = _to_float(getattr(po, "tax_amount", 0))
    shipping_amount = _to_float(getattr(po, "shipping_amount", 0))
    handling_amount = _to_float(getattr(po, "handling_amount", 0))

    custom_fields: list[dict[str, Any]] = []
    tax_field: dict[str, Any] = {"api_name": "cf_tax", "value": f"{tax_amount:.2f}"}
    if settings.zoho_po_cf_tax_id:
        tax_field["customfield_id"] = settings.zoho_po_cf_tax_id
    custom_fields.append(tax_field)

    shipping_field: dict[str, Any] = {
        "api_name": "cf_shipping_fee",
        "value": f"{shipping_amount:.2f}",
    }
    if settings.zoho_po_cf_shipping_fee_id:
        shipping_field["customfield_id"] = settings.zoho_po_cf_shipping_fee_id
    custom_fields.append(shipping_field)

    handling_field: dict[str, Any] = {
        "api_name": "cf_handling_fee",
        "value": f"{handling_amount:.2f}",
    }
    if settings.zoho_po_cf_handling_fee_id:
        handling_field["customfield_id"] = settings.zoho_po_cf_handling_fee_id
    custom_fields.append(handling_field)

    payload["custom_fields"] = custom_fields

    # Legacy/main org still relies on adjustment for S&H rollup.
    payload["adjustment"] = shipping_amount + handling_amount
    payload["adjustment_description"] = "Shipping Fee + Handling Fee"

    line_items: list[dict[str, Any]] = []
    for item in po.items or []:
        li: dict[str, Any] = {
            "name": item.external_item_name,
            "quantity": item.quantity,
            "rate": float(item.unit_price),
        }
        variant = getattr(item, "variant", None)
        if variant and variant.zoho_item_id:
            li["item_id"] = variant.zoho_item_id
        elif unmatched_item_id:
            li["item_id"] = unmatched_item_id
        line_items.append(li)
    payload["line_items"] = line_items

    return payload


async def _ensure_unmatched_placeholder_item(zoho: ZohoClient) -> Optional[str]:
    """Ensure the unmatched placeholder item exists in Zoho and return its item_id."""
    item = await zoho.ensure_item_by_sku(
        sku=UNMATCHED_PLACEHOLDER_ITEM_SKU,
        name=UNMATCHED_PLACEHOLDER_ITEM_NAME,
        rate=0.0,
        description="Auto-created placeholder for unmatched purchase-order lines.",
    )
    item_id = str(item.get("item_id") or "").strip()
    return item_id or None


def _is_billed_po_update_error(exc: Exception) -> bool:
    message = str(exc)
    return "36023" in message or "marked as billed" in message.lower()


def _is_bill_has_recorded_payments_delete_error(exc: Exception) -> bool:
    message = str(exc)
    return "1040" in message or "recorded payments cannot be deleted" in message.lower()


def _build_bill_recreate_payload(bill: dict[str, Any], *, purchaseorder_id: str) -> dict[str, Any]:
    """Build a safe bill-create payload from an existing Zoho bill payload."""
    payload: dict[str, Any] = {
        "purchaseorder_id": purchaseorder_id,
        "vendor_id": bill.get("vendor_id"),
        "bill_number": bill.get("bill_number"),
        "date": bill.get("date"),
        "due_date": bill.get("due_date"),
    }

    optional_keys = [
        "reference_number",
        "currency_id",
        "exchange_rate",
        "is_item_level_tax_calc",
        "is_inclusive_tax",
        "notes",
        "terms",
        "location_id",
        "custom_fields",
    ]
    for key in optional_keys:
        value = bill.get(key)
        if value is not None:
            payload[key] = value

    line_items_payload: list[dict[str, Any]] = []
    for line in bill.get("line_items") or []:
        if not isinstance(line, dict):
            continue
        line_payload: dict[str, Any] = {}
        for key in [
            "line_item_id",
            "purchaseorder_item_id",
            "receive_item_id",
            "item_id",
            "name",
            "description",
            "account_id",
            "rate",
            "quantity",
            "tax_id",
            "tds_tax_id",
            "location_id",
        ]:
            value = line.get(key)
            if value is not None and value != "":
                line_payload[key] = value

        if "quantity" not in line_payload:
            line_payload["quantity"] = line.get("quantity") or 1
        if "rate" not in line_payload and line.get("item_total") is not None:
            try:
                qty = float(line_payload.get("quantity") or 1)
                if qty > 0:
                    line_payload["rate"] = float(line.get("item_total")) / qty
            except Exception:
                pass

        if line_payload:
            line_items_payload.append(line_payload)

    payload["line_items"] = line_items_payload
    return payload


async def _update_billed_purchase_order_with_unbill_rebill(
    zoho: ZohoClient,
    *,
    purchase_order_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """
    Update a billed PO by deleting linked bills, updating PO, and recreating bills.

    This is intentionally scoped for explicit operator-triggered sync flows.
    """
    zoho_po = await zoho.get_purchase_order(purchase_order_id)
    bills = [b for b in (zoho_po.get("bills") or []) if isinstance(b, dict)]
    if not bills:
        # No linked bills; let normal update path surface any other failure reason.
        return await zoho.update_purchase_order(purchase_order_id, payload)

    bill_snapshots: list[dict[str, Any]] = []
    deleted_bill_ids: list[str] = []

    for bill_ref in bills:
        bill_id = str(bill_ref.get("bill_id") or "").strip()
        if not bill_id:
            continue
        full_bill = await zoho.get_bill(bill_id)
        if full_bill:
            for payment in full_bill.get("payments") or []:
                if isinstance(payment, dict):
                    await zoho.delete_bill_payment_reference(payment)

        try:
            await zoho.delete_bill(bill_id)
        except Exception as exc:
            if _is_bill_has_recorded_payments_delete_error(exc):
                # Retry once after pulling latest payment refs from Zoho.
                retry_bill = await zoho.get_bill(bill_id)
                for payment in retry_bill.get("payments") or []:
                    if isinstance(payment, dict):
                        await zoho.delete_bill_payment_reference(payment)
                await zoho.delete_bill(bill_id)
            else:
                raise

        if full_bill:
            bill_snapshots.append(full_bill)
        deleted_bill_ids.append(bill_id)

    # Some POs are non-billed but still locked due to receive records.
    receive_ids: list[str] = []
    page = 1
    while page <= 50:
        receives = await zoho.list_purchase_receives(
            purchaseorder_id=purchase_order_id,
            page=page,
            per_page=200,
        )
        if not receives:
            break

        for receive in receives:
            receive_id = str(
                (receive or {}).get("receive_id")
                or (receive or {}).get("purchasereceive_id")
                or ""
            ).strip()
            if receive_id:
                receive_ids.append(receive_id)

        if len(receives) < 200:
            break
        page += 1

    for receive_id in receive_ids:
        await zoho.delete_purchase_receive(receive_id)

    try:
        updated_po = await zoho.update_purchase_order(purchase_order_id, payload)
    except Exception:
        # Best-effort recovery: recreate deleted bills if PO update fails.
        for snapshot in bill_snapshots:
            recreate_payload = _build_bill_recreate_payload(snapshot, purchaseorder_id=purchase_order_id)
            try:
                await zoho.create_bill(recreate_payload)
            except Exception:
                logger.exception(
                    "sync_po_outbound: failed to restore bill after PO update failure | po_id=%s",
                    purchase_order_id,
                )
        raise

    for snapshot in bill_snapshots:
        recreate_payload = _build_bill_recreate_payload(snapshot, purchaseorder_id=purchase_order_id)
        await zoho.create_bill(recreate_payload)

    logger.warning(
        "sync_po_outbound: billed/received PO required unbill-receive-rebill flow | po_id=%s bills_processed=%s receives_deleted=%s",
        purchase_order_id,
        len(deleted_bill_ids),
        len(receive_ids),
    )
    return updated_po


# =========================================================================
# INBOUND MAPPERS  (Zoho → USAV)
# =========================================================================

def zoho_contact_to_customer_fields(data: dict) -> dict[str, Any]:
    """Extract Customer-relevant fields from a Zoho contact payload."""
    fields: dict[str, Any] = {}
    if "contact_name" in data:
        fields["name"] = data["contact_name"]
    if "email" in data:
        fields["email"] = data["email"]
    if "phone" in data:
        fields["phone"] = data["phone"]
    if "company_name" in data:
        fields["company_name"] = data["company_name"]
    addr = data.get("billing_address") or {}
    if addr.get("address"):
        fields["address_line1"] = addr["address"]
    if addr.get("street2"):
        fields["address_line2"] = addr["street2"]
    if addr.get("city"):
        fields["city"] = addr["city"]
    if addr.get("state"):
        fields["state"] = addr["state"]
    if addr.get("zip"):
        fields["postal_code"] = addr["zip"]
    if addr.get("country"):
        fields["country"] = addr["country"]
    return fields


# =========================================================================
# OUTBOUND SYNC WORKERS
# =========================================================================

async def sync_variant_outbound(variant_id: int) -> None:
    """
    Push a single ``ProductVariant`` to Zoho Inventory (create or update).

    Uses a fresh DB session so it is safe to call from a background task.
    """
    from sqlalchemy.orm import selectinload
    from sqlalchemy import select
    from app.models.entities import ProductIdentity

    async with async_session_factory() as db:
        stmt = (
            select(ProductVariant)
            .options(
                selectinload(ProductVariant.identity).selectinload(ProductIdentity.family),
                selectinload(ProductVariant.listings),
            )
            .where(ProductVariant.id == variant_id)
        )
        variant = (await db.execute(stmt)).scalar_one_or_none()
        if variant is None:
            logger.warning("sync_variant_outbound: variant %s not found", variant_id)
            return

        payload = variant_to_zoho_payload(variant)
        new_hash = generate_payload_hash(payload)

        if new_hash == variant.zoho_last_sync_hash:
            logger.debug("sync_variant_outbound: variant %s unchanged (hash match)", variant_id)
            return

        try:
            zoho = ZohoClient()
            zoho_item = await zoho.sync_item(
                sku=payload.get("sku", variant.full_sku),
                name=payload.get("name", variant.full_sku),
                rate=float(payload.get("rate", 0) or 0),
                description=payload.get("description", ""),
                **{k: v for k, v in payload.items() if k not in {"name", "sku", "rate", "description"}},
            )

            zoho_item_id = str(zoho_item.get("item_id", ""))
            if zoho_item_id:
                variant.zoho_item_id = zoho_item_id

            variant.zoho_last_sync_hash = new_hash
            variant.zoho_last_synced_at = datetime.now()
            variant.zoho_sync_error = None
            await db.commit()

            logger.info(
                "sync_variant_outbound: variant %s synced to Zoho (item_id=%s)",
                variant_id,
                zoho_item_id,
            )
        except RateLimitError as exc:
            variant.zoho_sync_error = str(exc)
            await db.commit()
            logger.warning("sync_variant_outbound: variant %s rate-limited (retry_after=%s)", variant_id, getattr(exc, "retry_after", None))
            raise
        except Exception as exc:
            variant.zoho_sync_error = str(exc)[:2000]
            await db.commit()
            logger.exception("sync_variant_outbound: variant %s failed", variant_id)


async def sync_customer_outbound(customer_id: int) -> None:
    """
    Push a single ``Customer`` to Zoho Inventory *Contacts* (create or update).
    """
    from sqlalchemy import select

    async with async_session_factory() as db:
        customer = (await db.execute(
            select(Customer).where(Customer.id == customer_id)
        )).scalar_one_or_none()

        if customer is None:
            logger.warning("sync_customer_outbound: customer %s not found", customer_id)
            return

        payload = customer_to_zoho_payload(customer)
        new_hash = generate_payload_hash(payload)

        if new_hash == customer.zoho_last_sync_hash:
            logger.debug("sync_customer_outbound: customer %s unchanged (hash match)", customer_id)
            return

        try:
            zoho = ZohoClient()

            # If no zoho_id but email exists, try to find existing contact by email first
            if not customer.zoho_id and customer.email:
                existing = await zoho.get_contact_by_email(customer.email)
                if existing:
                    customer.zoho_id = str(existing.get("contact_id", ""))

            if customer.zoho_id:
                contact = await zoho.update_contact(customer.zoho_id, payload)
            else:
                contact = await zoho.create_contact(payload)

            contact_id = str(contact.get("contact_id", ""))
            if contact_id:
                customer.zoho_id = contact_id

            # Soft-delete mapping
            if customer.is_active:
                if customer.zoho_id:
                    await zoho.mark_contact_active(customer.zoho_id)
            else:
                if customer.zoho_id:
                    await zoho.mark_contact_inactive(customer.zoho_id)

            customer.zoho_last_sync_hash = new_hash
            customer.zoho_last_synced_at = datetime.now()
            customer.zoho_sync_error = None
            customer._updated_by_sync = True
            await db.commit()

            logger.info(
                "sync_customer_outbound: customer %s synced to Zoho (contact_id=%s)",
                customer_id,
                customer.zoho_id,
            )
        except Exception as exc:
            message = str(exc)
            # Handle duplicate name error by looking up existing contact
            if "3062" in message or "already exists" in message:
                zoho = ZohoClient()
                resolved_id: Optional[str] = None

                if customer.email:
                    existing = await zoho.get_contact_by_email(customer.email)
                    if existing:
                        resolved_id = str(existing.get("contact_id", ""))

                if not resolved_id and customer.name:
                    # Fallback: scan first page of contacts for matching name
                    contacts = await zoho.list_contacts(page=1, per_page=200)
                    for c in contacts:
                        if c.get("contact_name") == customer.name:
                            resolved_id = str(c.get("contact_id", ""))
                            break

                if resolved_id:
                    customer.zoho_id = resolved_id
                    customer.zoho_last_sync_hash = new_hash
                    customer.zoho_last_synced_at = datetime.now()
                    customer.zoho_sync_error = None
                    customer._updated_by_sync = True
                    await db.commit()
                    logger.info(
                        "sync_customer_outbound: customer %s linked to existing Zoho contact %s",
                        customer_id,
                        resolved_id,
                    )
                    return

            customer.zoho_sync_error = message[:2000]
            customer._updated_by_sync = True
            await db.commit()
            logger.exception("sync_customer_outbound: customer %s failed", customer_id)


async def sync_vendor_outbound(vendor_id: int) -> None:
    """Push a single ``Vendor`` to Zoho as a vendor contact."""
    from sqlalchemy import select

    async with async_session_factory() as db:
        vendor = (await db.execute(select(Vendor).where(Vendor.id == vendor_id))).scalar_one_or_none()
        if vendor is None:
            logger.warning("sync_vendor_outbound: vendor %s not found", vendor_id)
            return

        payload = vendor_to_zoho_payload(vendor)
        new_hash = generate_payload_hash(payload)

        if new_hash == vendor.zoho_last_sync_hash:
            logger.debug("sync_vendor_outbound: vendor %s unchanged (hash match)", vendor_id)
            return

        try:
            zoho = ZohoClient()

            if not vendor.zoho_id and vendor.email:
                existing = await zoho.get_contact_by_email(vendor.email)
                if existing and str(existing.get("contact_type", "")).lower() == "vendor":
                    vendor.zoho_id = str(existing.get("contact_id", ""))

            if vendor.zoho_id:
                contact = await zoho.update_contact(vendor.zoho_id, payload)
            else:
                contact = await zoho.create_contact(payload, contact_type="vendor")

            contact_id = str(contact.get("contact_id", ""))
            if contact_id:
                vendor.zoho_id = contact_id

            if vendor.zoho_id:
                if vendor.is_active:
                    await zoho.mark_contact_active(vendor.zoho_id)
                else:
                    await zoho.mark_contact_inactive(vendor.zoho_id)

            vendor.zoho_last_sync_hash = new_hash
            vendor.zoho_last_synced_at = datetime.now()
            vendor.zoho_sync_error = None
            vendor._updated_by_sync = True
            await db.commit()

            logger.info(
                "sync_vendor_outbound: vendor %s synced to Zoho (contact_id=%s)",
                vendor_id,
                vendor.zoho_id,
            )
        except Exception as exc:
            vendor.zoho_sync_error = str(exc)[:2000]
            vendor._updated_by_sync = True
            await db.commit()
            logger.exception("sync_vendor_outbound: vendor %s failed", vendor_id)


async def sync_po_outbound(po_id: int, allow_billed_unbill_rebill: bool = False) -> None:
    """Push a ``PurchaseOrder`` to Zoho Inventory as a purchase order."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    async with async_session_factory() as db:
        stmt = (
            select(PurchaseOrder)
            .options(
                selectinload(PurchaseOrder.vendor),
                selectinload(PurchaseOrder.items).selectinload(PurchaseOrderItem.variant),
            )
            .where(PurchaseOrder.id == po_id)
        )
        po = (await db.execute(stmt)).scalar_one_or_none()
        if po is None:
            logger.warning("sync_po_outbound: purchase_order %s not found", po_id)
            return

        po.zoho_sync_status = ZohoSyncStatus.PENDING
        po._updated_by_sync = True
        await db.commit()
        po._updated_by_sync = False

        vendor = po.vendor
        if vendor is None:
            po.zoho_sync_error = "Cannot sync purchase order: no linked vendor"
            po.zoho_sync_status = ZohoSyncStatus.ERROR
            po._updated_by_sync = True
            await db.commit()
            return

        if not vendor.zoho_id:
            await sync_vendor_outbound(vendor.id)
            await db.refresh(vendor)
            if not vendor.zoho_id:
                po.zoho_sync_error = f"Vendor {vendor.id} missing zoho_id; sync vendor first."
                po.zoho_sync_status = ZohoSyncStatus.ERROR
                po._updated_by_sync = True
                await db.commit()
                return

        try:
            zoho = ZohoClient()

            unmatched_item_id: Optional[str] = None
            if any(getattr(item, "variant", None) is None for item in (po.items or [])):
                unmatched_item_id = await _ensure_unmatched_placeholder_item(zoho)
                if not unmatched_item_id:
                    raise ValueError(
                        "Unable to resolve Zoho placeholder item for unmatched purchase-order lines"
                    )

            payload = purchase_order_to_zoho_payload(po, unmatched_item_id=unmatched_item_id)
            new_hash = generate_payload_hash(payload)

            if new_hash == po.zoho_last_sync_hash:
                logger.debug("sync_po_outbound: purchase_order %s unchanged (hash match)", po_id)
                po.zoho_sync_error = None
                po.zoho_sync_status = ZohoSyncStatus.SYNCED
                po._updated_by_sync = True
                await db.commit()
                return

            if po.zoho_id:
                try:
                    existing_po = await zoho.get_purchase_order(po.zoho_id)
                    if not existing_po:
                        po.zoho_id = None
                except Exception as lookup_exc:
                    logger.warning(
                        "sync_po_outbound: verification of existing purchase order %s failed: %s",
                        po.zoho_id,
                        lookup_exc,
                    )

            if not po.zoho_id:
                try:
                    existing_po = await zoho.find_purchase_order_by_number(po.po_number)
                    if existing_po:
                        po.zoho_id = str(existing_po.get("purchaseorder_id") or "").strip() or None
                except Exception as lookup_exc:
                    logger.warning(
                        "sync_po_outbound: lookup existing purchase order failed: %s",
                        lookup_exc,
                    )

            if po.zoho_id:
                try:
                    zoho_po = await zoho.update_purchase_order(po.zoho_id, payload)
                except Exception as update_exc:
                    if allow_billed_unbill_rebill and _is_billed_po_update_error(update_exc):
                        zoho_po = await _update_billed_purchase_order_with_unbill_rebill(
                            zoho,
                            purchase_order_id=po.zoho_id,
                            payload=payload,
                        )
                    else:
                        raise
            else:
                zoho_po = await zoho.create_purchase_order(payload)

            zoho_po_id = str(zoho_po.get("purchaseorder_id", ""))
            if zoho_po_id:
                po.zoho_id = zoho_po_id

            po.zoho_last_sync_hash = new_hash
            po.zoho_last_synced_at = datetime.now()
            po.zoho_sync_error = None
            po.zoho_sync_status = ZohoSyncStatus.SYNCED
            po._updated_by_sync = True
            await db.commit()

            logger.info(
                "sync_po_outbound: purchase_order %s synced to Zoho (purchaseorder_id=%s)",
                po_id,
                po.zoho_id,
            )
        except Exception as exc:
            po.zoho_sync_error = str(exc)[:2000]
            po.zoho_sync_status = ZohoSyncStatus.ERROR
            po._updated_by_sync = True
            await db.commit()
            logger.exception("sync_po_outbound: purchase_order %s failed", po_id)


async def sync_po_outbound_with_unbill_rebill(po_id: int) -> None:
    """Operator-triggered PO sync that allows unbill/rebill for billed Zoho purchase orders."""
    await sync_po_outbound(po_id, allow_billed_unbill_rebill=True)


# =========================================================================
# INBOUND SYNC WORKERS  (called by webhook dispatcher)
# =========================================================================

async def process_item_inbound(payload: dict) -> None:
    """
    Apply an inbound Zoho item webhook to the local ``ProductVariant``.

    Echo-loop prevention:
    1. Hash the incoming payload — if it matches ``zoho_last_sync_hash``, skip.
    2. Set ``_updated_by_sync = True`` on the entity before commit so that
       the ``after_update`` listener does not re-enqueue an outbound sync.
    """
    from sqlalchemy import select

    item_data = payload.get("item") or payload
    zoho_item_id = str(item_data.get("item_id", ""))
    sku = item_data.get("sku", "")

    if not zoho_item_id and not sku:
        logger.warning("process_item_inbound: payload missing item_id and sku")
        return

    new_hash = generate_payload_hash(item_data)

    async with async_session_factory() as db:
        # Locate by zoho_item_id first, fallback to SKU
        stmt = select(ProductVariant)
        if zoho_item_id:
            stmt = stmt.where(ProductVariant.zoho_item_id == zoho_item_id)
        else:
            stmt = stmt.where(ProductVariant.full_sku == sku)

        variant = (await db.execute(stmt)).scalar_one_or_none()
        if variant is None:
            logger.info("process_item_inbound: no local variant for zoho_item_id=%s sku=%s", zoho_item_id, sku)
            return

        if variant.zoho_last_sync_hash == new_hash:
            logger.debug("process_item_inbound: variant %s hash unchanged, skipping", variant.id)
            return

        # Apply fields we care about
        if item_data.get("name"):
            variant.variant_name = item_data["name"]
        if item_data.get("status") == "inactive":
            variant.is_active = False
        elif item_data.get("status") == "active":
            variant.is_active = True

        variant.zoho_item_id = zoho_item_id or variant.zoho_item_id
        variant.zoho_last_sync_hash = new_hash
        variant.zoho_last_synced_at = datetime.now()
        variant.zoho_sync_error = None

        # CRITICAL: prevent echo loop
        variant._updated_by_sync = True
        await db.commit()

        logger.info("process_item_inbound: variant %s updated from Zoho", variant.id)


async def process_contact_inbound(payload: dict) -> None:
    """
    Apply an inbound Zoho contact webhook to the local ``Customer``.
    """
    from sqlalchemy import select

    contact_data = payload.get("contact") or payload
    zoho_contact_id = str(contact_data.get("contact_id", ""))

    if not zoho_contact_id:
        logger.warning("process_contact_inbound: missing contact_id in payload")
        return

    new_hash = generate_payload_hash(contact_data)

    async with async_session_factory() as db:
        stmt = select(Customer).where(Customer.zoho_id == zoho_contact_id)
        customer = (await db.execute(stmt)).scalar_one_or_none()

        if customer is None:
            # New contact from Zoho — create locally
            fields = zoho_contact_to_customer_fields(contact_data)
            customer = Customer(
                zoho_id=zoho_contact_id,
                zoho_last_sync_hash=new_hash,
                zoho_last_synced_at=datetime.now(),
                **fields,
            )
            customer._updated_by_sync = True
            db.add(customer)
            await db.commit()
            logger.info("process_contact_inbound: created customer from Zoho contact %s", zoho_contact_id)
            return

        if customer.zoho_last_sync_hash == new_hash:
            logger.debug("process_contact_inbound: customer %s hash unchanged", customer.id)
            return

        fields = zoho_contact_to_customer_fields(contact_data)
        for key, value in fields.items():
            setattr(customer, key, value)

        customer.zoho_last_sync_hash = new_hash
        customer.zoho_last_synced_at = datetime.now()
        customer.zoho_sync_error = None
        customer._updated_by_sync = True
        await db.commit()

        logger.info("process_contact_inbound: customer %s updated from Zoho", customer.id)


# =========================================================================
# ORDER OUTBOUND SYNC  (dependency-aware)
# =========================================================================

_ORDER_SYNC_MAX_RETRIES = 1  # retained for reference; no auto-retry to preserve Zoho API quota
_ORDER_SYNC_RETRY_DELAY_SECS = 0


def order_to_zoho_payload(order: Order) -> dict[str, Any]:
    """Build a Zoho SalesOrder payload from a local ``Order``."""
    # Hard guard: Zoho requires an existing contact; fail fast if missing
    customer: Optional[Customer] = getattr(order, "customer", None)
    if not (customer and customer.zoho_id):
        raise ValueError("Order is missing customer.zoho_id; sync customer first.")

    payload: dict[str, Any] = {
        "reference_number": order.external_order_id,
        "date": (order.ordered_at or order.created_at).strftime("%Y-%m-%d"),
    }

    # Customer
    payload["customer_id"] = customer.zoho_id

    # Line items
    line_items: list[dict[str, Any]] = []
    for item in (order.items or []):
        li: dict[str, Any] = {
            "name": item.item_name,
            "quantity": item.quantity,
            "rate": float(item.unit_price),
        }
        variant = getattr(item, "variant", None)
        if variant and variant.zoho_item_id:
            li["item_id"] = variant.zoho_item_id
        line_items.append(li)
    payload["line_items"] = line_items

    # Shipping address
    addr_fields = {
        "address": order.shipping_address_line1,
        "street2": order.shipping_address_line2,
        "city": order.shipping_city,
        "state": order.shipping_state,
        "zip": order.shipping_postal_code,
        "country": order.shipping_country,
    }
    shipping = {k: v for k, v in addr_fields.items() if v}
    if shipping:
        payload["shipping_address"] = _sanitize_shipping_address(shipping)

    return payload


def _sanitize_shipping_address(addr: dict[str, str]) -> dict[str, str]:
    """Trim shipping address fields to satisfy Zoho < 100 chars rule."""
    max_total = 95  # keep some headroom below 100
    max_field = 64

    def _trim(value: str, limit: int) -> str:
        return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"

    sanitized = {k: _trim(v, max_field) for k, v in addr.items() if v}

    # Helper to measure total length Zoho seems to enforce (concatenated fields)
    def _total_len(parts: dict[str, str]) -> int:
        ordered = [parts[k] for k in ("address", "street2", "city", "state", "zip", "country") if k in parts]
        return len(", ".join(ordered))

    # First, if total length still exceeds the threshold, drop street2 entirely.
    if _total_len(sanitized) > max_total and "street2" in sanitized:
        sanitized.pop("street2")

    # If still too long, trim the main address field down until we fit or empty.
    if _total_len(sanitized) > max_total and "address" in sanitized:
        while _total_len(sanitized) > max_total and sanitized.get("address"):
            sanitized["address"] = sanitized["address"][:-1]
        if sanitized.get("address") == "":
            sanitized.pop("address")

    return {k: v for k, v in sanitized.items() if v}


async def sync_order_outbound(order_id: int) -> None:
    """
    Push a single ``Order`` to Zoho as a SalesOrder.

    **Dependency checks:**
    - If the linked Customer has no ``zoho_id``, trigger customer sync first
      and requeue with a delay.
    - If any line-item's ProductVariant has no ``zoho_item_id``, trigger
      variant sync first and requeue.
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    async with async_session_factory() as db:
        stmt = (
            select(Order)
            .options(
                selectinload(Order.customer),
                selectinload(Order.items).selectinload(OrderItem.variant),
            )
            .where(Order.id == order_id)
        )
        order = (await db.execute(stmt)).scalar_one_or_none()
        if order is None:
            logger.warning("sync_order_outbound: order %s not found", order_id)
            return

        # Mark as actively syncing
        order.zoho_sync_status = ZohoSyncStatus.PENDING
        order._updated_by_sync = True
        await db.commit()
        order._updated_by_sync = False

        # ---- DEPENDENCY: Customer must exist and have zoho_id ----
        customer = order.customer
        if customer is None:
            order.zoho_sync_error = "Cannot sync order: no linked customer record."
            order.zoho_sync_status = ZohoSyncStatus.ERROR
            order._updated_by_sync = True
            await db.commit()
            logger.error("sync_order_outbound: order %s has no customer", order_id)
            return

        if not customer.zoho_id:
            logger.info(
                "sync_order_outbound: order %s waiting on customer %s zoho_id",
                order_id, customer.id,
            )
            await sync_customer_outbound(customer.id)
            await db.refresh(customer)

            if not customer.zoho_id:
                order.zoho_sync_error = f"Customer {customer.id} missing zoho_id; sync customer first."
                order.zoho_sync_status = ZohoSyncStatus.ERROR
                order._updated_by_sync = True
                await db.commit()
                return

        # ---- DEPENDENCY: All line-item variants must have zoho_item_id ----
        missing_variants: list[int] = []
        for item in (order.items or []):
            variant = getattr(item, "variant", None)
            if variant and not variant.zoho_item_id:
                missing_variants.append(variant.id)

        if missing_variants:
            logger.info(
                "sync_order_outbound: order %s waiting on %d variants",
                order_id, len(missing_variants),
            )
            for vid in missing_variants:
                try:
                    await sync_variant_outbound(vid)
                except RateLimitError as exc:
                    order.zoho_sync_error = f"Zoho rate limit while syncing variants; retry after {getattr(exc, 'retry_after', 60)}s."
                    order.zoho_sync_status = ZohoSyncStatus.ERROR
                    order._updated_by_sync = True
                    await db.commit()
                    return
            # Refresh variants and re-check once
            refreshed_missing: list[int] = []
            for item in (order.items or []):
                variant = getattr(item, "variant", None)
                if variant:
                    await db.refresh(variant)
                    if not variant.zoho_item_id:
                        refreshed_missing.append(variant.id)

            if refreshed_missing:
                order.zoho_sync_error = (
                    f"Variants {refreshed_missing} missing zoho_item_id; sync variants first."
                )
                order.zoho_sync_status = ZohoSyncStatus.ERROR
                order._updated_by_sync = True
                await db.commit()
                return

        # ---- All dependencies met: build payload & push ----
        payload = order_to_zoho_payload(order)
        new_hash = generate_payload_hash(payload)

        if new_hash == order.zoho_last_sync_hash:
            logger.debug("sync_order_outbound: order %s unchanged (hash match)", order_id)
            order.zoho_sync_status = ZohoSyncStatus.SYNCED
            order.zoho_sync_error = None
            order._updated_by_sync = True
            await db.commit()
            order._updated_by_sync = False
            return

        try:
            zoho = ZohoClient()

            # If we don't yet have a zoho_id, try to locate an existing SalesOrder
            # by reference_number to avoid duplicates when re-queuing the same order.
            if not order.zoho_id:
                existing_so_id: Optional[str] = None
                try:
                    for page in range(1, 4):  # scan first ~600 orders to keep quota safe
                        salesorders = await zoho.list_salesorders(page=page, per_page=200)
                        match = next(
                            (
                                so
                                for so in salesorders
                                if str(so.get("reference_number", "")) == order.external_order_id
                            ),
                            None,
                        )
                        if match:
                            existing_so_id = str(match.get("salesorder_id", "")) or None
                            break
                        if len(salesorders) < 200:
                            break  # no more pages
                except Exception as lookup_exc:
                    logger.warning(
                        "sync_order_outbound: lookup existing salesorder failed: %s",
                        lookup_exc,
                    )

                if existing_so_id:
                    order.zoho_id = existing_so_id

            if order.zoho_id:
                so = await zoho.update_salesorder(order.zoho_id, payload)
            else:
                so = await zoho.create_sales_order(payload)

            so_id = str(so.get("salesorder_id", ""))
            if so_id:
                order.zoho_id = so_id

            order.zoho_last_sync_hash = new_hash
            order.zoho_last_synced_at = datetime.now()
            order.zoho_sync_error = None
            order.zoho_sync_status = ZohoSyncStatus.SYNCED
            order._updated_by_sync = True
            await db.commit()
            order._updated_by_sync = False

            logger.info(
                "sync_order_outbound: order %s synced to Zoho (salesorder_id=%s)",
                order_id, so_id,
            )

            # After the sales order is synced, apply shipping-specific actions
            from app.modules.orders.models import ShippingStatus
            if order.shipping_status in (
                ShippingStatus.PACKED,
                ShippingStatus.SHIPPING,
                ShippingStatus.DELIVERED,
            ):
                try:
                    await sync_shipping_status_to_zoho(order_id)
                except Exception as ship_exc:
                    logger.warning(
                        "sync_order_outbound: shipping status sync failed for order %s: %s",
                        order_id, ship_exc,
                    )
        except RateLimitError as exc:
            order.zoho_sync_error = (
                f"Zoho rate limit hit; retry after {getattr(exc, 'retry_after', 60)}s."
            )[:2000]
            order.zoho_sync_status = ZohoSyncStatus.ERROR
            order._updated_by_sync = True
            await db.commit()
            logger.warning("sync_order_outbound: order %s rate-limited", order_id)
            return
        except Exception as exc:
            logger.error(
                "sync_order_outbound: order %s payload failed | payload=%s",
                order_id,
                payload,
            )
            order.zoho_sync_error = str(exc)[:2000]
            order.zoho_sync_status = ZohoSyncStatus.ERROR
            order._updated_by_sync = True
            await db.commit()
            logger.exception("sync_order_outbound: order %s failed", order_id)


# =========================================================================
# SHIPPING STATUS SYNC  (Package / Shipment / Delivered)
# =========================================================================

async def sync_shipping_status_to_zoho(order_id: int) -> None:
    """
    Push the local shipping status to Zoho as package / shipment actions.

    - PACKED or SHIPPING → ensure a package exists (marks SO as "packed").
    - SHIPPING → also create a shipment order if none exists.
    - DELIVERED → ensure a shipment exists and mark it as delivered.
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from app.modules.orders.models import ShippingStatus

    async with async_session_factory() as db:
        stmt = (
            select(Order)
            .options(
                selectinload(Order.customer),
                selectinload(Order.items).selectinload(OrderItem.variant),
            )
            .where(Order.id == order_id)
        )
        order = (await db.execute(stmt)).scalar_one_or_none()
        if order is None:
            logger.warning("sync_shipping_status: order %s not found", order_id)
            return

        if not order.zoho_id:
            logger.info("sync_shipping_status: order %s has no zoho_id — sync order first", order_id)
            return

        zoho = ZohoClient()

        try:
            if order.shipping_status in (
                ShippingStatus.PACKED,
                ShippingStatus.SHIPPING,
                ShippingStatus.DELIVERED,
            ):
                # Ensure a package exists (idempotent — skip if already present)
                existing_packages = await zoho.list_packages(order.zoho_id)
                if not existing_packages:
                    # Fetch the full SO to get line_item IDs
                    so = await zoho.get_salesorder(order.zoho_id)
                    so_line_items = so.get("line_items", [])
                    pkg_lines = [
                        {
                            "so_line_item_id": li["line_item_id"],
                            "quantity": li.get("quantity", 1),
                        }
                        for li in so_line_items
                        if li.get("line_item_id")
                    ]
                    if pkg_lines:
                        await zoho.create_package(order.zoho_id, pkg_lines)
                        logger.info("sync_shipping_status: created package for order %s", order_id)
                    else:
                        logger.warning(
                            "sync_shipping_status: order %s SO has no line items for packaging",
                            order_id,
                        )

            if order.shipping_status in (ShippingStatus.SHIPPING, ShippingStatus.DELIVERED):
                # Ensure a shipment order exists
                existing_shipments = await zoho.list_shipment_orders(order.zoho_id)
                if not existing_shipments:
                    packages = await zoho.list_packages(order.zoho_id)
                    pkg_ids = [str(p.get("package_id", "")) for p in packages if p.get("package_id")]
                    if pkg_ids:
                        await zoho.create_shipment_order(
                            order.zoho_id,
                            pkg_ids,
                            tracking_number=order.tracking_number,
                            delivery_method=order.carrier,
                        )
                        logger.info("sync_shipping_status: created shipment for order %s", order_id)

            if order.shipping_status == ShippingStatus.DELIVERED:
                shipments = await zoho.list_shipment_orders(order.zoho_id)
                for shipment in shipments:
                    so_status = str(shipment.get("status", "")).lower()
                    if so_status != "delivered":
                        shipment_id = str(shipment.get("shipment_id", ""))
                        if shipment_id:
                            await zoho.mark_shipment_delivered(shipment_id)
                            logger.info(
                                "sync_shipping_status: marked shipment %s delivered for order %s",
                                shipment_id, order_id,
                            )

            # Mark order as synced
            order.zoho_sync_status = ZohoSyncStatus.SYNCED
            order.zoho_sync_error = None
            order.zoho_last_synced_at = datetime.now()
            order._updated_by_sync = True
            await db.commit()
            order._updated_by_sync = False

        except RateLimitError as exc:
            order.zoho_sync_error = (
                f"Zoho rate limit during shipping sync; retry after {getattr(exc, 'retry_after', 60)}s."
            )[:2000]
            order.zoho_sync_status = ZohoSyncStatus.ERROR
            order._updated_by_sync = True
            await db.commit()
            logger.warning("sync_shipping_status: order %s rate-limited", order_id)
        except Exception as exc:
            order.zoho_sync_error = str(exc)[:2000]
            order.zoho_sync_status = ZohoSyncStatus.ERROR
            order._updated_by_sync = True
            await db.commit()
            logger.exception("sync_shipping_status: order %s failed", order_id)


# =========================================================================
# ORDER INBOUND SYNC
# =========================================================================

async def process_order_inbound(payload: dict) -> None:
    """
    Apply an inbound Zoho SalesOrder webhook to the local ``Order``.

    Only updates *status* and selected metadata fields — we do NOT
    overwrite line-items from the Zoho side.
    """
    from sqlalchemy import select

    so_data = payload.get("salesorder") or payload
    zoho_so_id = str(so_data.get("salesorder_id", ""))

    if not zoho_so_id:
        logger.warning("process_order_inbound: missing salesorder_id")
        return

    new_hash = generate_payload_hash(so_data)

    async with async_session_factory() as db:
        stmt = select(Order).where(Order.zoho_id == zoho_so_id)
        order = (await db.execute(stmt)).scalar_one_or_none()
        if order is None:
            logger.info("process_order_inbound: no local order for zoho_id=%s", zoho_so_id)
            return

        if order.zoho_last_sync_hash == new_hash:
            logger.debug("process_order_inbound: order %s hash unchanged", order.id)
            return

        # Map Zoho status → local status (broad mapping)
        _ZOHO_STATUS_MAP = {
            "draft": "PENDING",
            "confirmed": "PROCESSING",
            "packed": "READY_TO_SHIP",
            "shipped": "SHIPPED",
            "delivered": "DELIVERED",
            "void": "CANCELLED",
        }
        zoho_status = so_data.get("status", "").lower()
        if zoho_status in _ZOHO_STATUS_MAP:
            from app.modules.orders.models import OrderStatus
            order.status = OrderStatus(_ZOHO_STATUS_MAP[zoho_status])

        # Map Zoho status → local shipping status
        _ZOHO_SHIPPING_MAP = {
            "packed": "PACKED",
            "shipped": "SHIPPING",
            "delivered": "DELIVERED",
            "void": "CANCELLED",
        }
        if zoho_status in _ZOHO_SHIPPING_MAP:
            from app.modules.orders.models import ShippingStatus
            order.shipping_status = ShippingStatus(_ZOHO_SHIPPING_MAP[zoho_status])

        order.zoho_last_sync_hash = new_hash
        order.zoho_last_synced_at = datetime.now()
        order.zoho_sync_error = None
        order.zoho_sync_status = ZohoSyncStatus.SYNCED
        order._updated_by_sync = True
        await db.commit()

        logger.info("process_order_inbound: order %s updated from Zoho", order.id)


# =========================================================================
# BACKGROUND TASK DISPATCHING HELPERS
# =========================================================================

def _enqueue_variant_sync(variant_id: int) -> None:
    """Fire-and-forget background task for variant outbound sync."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(sync_variant_outbound(variant_id))
    except RuntimeError:
        logger.debug("_enqueue_variant_sync: no running event loop, skipping")


def _enqueue_customer_sync(customer_id: int) -> None:
    """Fire-and-forget background task for customer outbound sync."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(sync_customer_outbound(customer_id))
    except RuntimeError:
        logger.debug("_enqueue_customer_sync: no running event loop, skipping")


def _enqueue_order_sync(order_id: int) -> None:
    """Fire-and-forget background task for order outbound sync."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(sync_order_outbound(order_id))
    except RuntimeError:
        logger.debug("_enqueue_order_sync: no running event loop, skipping")


def _enqueue_vendor_sync(vendor_id: int) -> None:
    """Fire-and-forget background task for vendor outbound sync."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(sync_vendor_outbound(vendor_id))
    except RuntimeError:
        logger.debug("_enqueue_vendor_sync: no running event loop, skipping")


def _enqueue_po_sync(po_id: int) -> None:
    """Fire-and-forget background task for purchase-order outbound sync."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(sync_po_outbound(po_id))
    except RuntimeError:
        logger.debug("_enqueue_po_sync: no running event loop, skipping")


# =========================================================================
# SQLALCHEMY EVENT LISTENERS
# =========================================================================

def _on_variant_after_write(mapper, connection, target: ProductVariant):
    """Enqueue outbound sync unless this write originated from an inbound sync."""
    if target._updated_by_sync:
        return
    _enqueue_variant_sync(target.id)


def _on_customer_after_write(mapper, connection, target: Customer):
    """Enqueue outbound sync unless this write originated from an inbound sync."""
    if target._updated_by_sync:
        return
    _enqueue_customer_sync(target.id)


def _on_order_after_write(mapper, connection, target: Order):
    """Enqueue outbound sync unless this write originated from an inbound sync."""
    if target._updated_by_sync:
        return
    _enqueue_order_sync(target.id)


def _on_vendor_after_write(mapper, connection, target: Vendor):
    """Enqueue vendor outbound sync unless this write came from inbound sync."""
    if target._updated_by_sync:
        return
    _enqueue_vendor_sync(target.id)


def _on_purchase_order_after_write(mapper, connection, target: PurchaseOrder):
    """Enqueue purchase-order outbound sync unless this write came from inbound sync."""
    if target._updated_by_sync:
        return
    _enqueue_po_sync(target.id)


def register_sync_listeners() -> None:
    """
    Attach SQLAlchemy ``after_insert`` / ``after_update`` listeners.

    Call once at application startup (e.g. inside the lifespan handler).
    """
    event.listen(ProductVariant, "after_insert", _on_variant_after_write)
    event.listen(ProductVariant, "after_update", _on_variant_after_write)
    event.listen(Customer, "after_insert", _on_customer_after_write)
    event.listen(Customer, "after_update", _on_customer_after_write)
    event.listen(Order, "after_insert", _on_order_after_write)
    event.listen(Order, "after_update", _on_order_after_write)
    event.listen(Vendor, "after_insert", _on_vendor_after_write)
    event.listen(Vendor, "after_update", _on_vendor_after_write)
    event.listen(PurchaseOrder, "after_insert", _on_purchase_order_after_write)
    event.listen(PurchaseOrder, "after_update", _on_purchase_order_after_write)
    logger.info("Zoho sync event listeners registered")
