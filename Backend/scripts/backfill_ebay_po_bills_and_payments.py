#!/usr/bin/env python
"""Backfill Zoho bills and vendor payments from local eBay purchase orders.

Scope:
- Source purchase orders: eBay purchase imports only.
- Date window: defaults to 2026-03-01 through today.
- For each eligible PO, create:
  1) Bill (bill_number/ref/date from po_number/order_date)
  2) Vendor payment (date/order_date, payment mode, paid-through account)

Safety:
- Default mode is dry-run. Use --apply to execute writes.
- Idempotency checks skip bill/payment when already present.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from types import MethodType
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import noload, selectinload

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.database import async_session_factory
from app.integrations.zoho.client import ZohoClient
from app.models.entities import ProductVariant
from app.models.purchasing import PurchaseOrder, PurchaseOrderItem

EBAY_PO_SOURCES = {
    "EBAY_MEKONG_API",
    "EBAY_PURCHASING_API",
    "EBAY_USAV_API",
    "EBAY_DRAGON_API",
}
PAYMENT_TERMS_DUE_ON_RECEIPT = 0
PAID_THROUGH_ACCOUNT_ID_GOODS_IN_TRANSIT = "5623409000001937358"


@dataclass
class Stats:
    scanned: int = 0
    eligible: int = 0
    skipped_existing_bill: int = 0
    skipped_existing_payment: int = 0
    would_create_bills: int = 0
    created_bills: int = 0
    would_create_payments: int = 0
    created_payments: int = 0
    failed: int = 0
    failures: list[str] = field(default_factory=list)


def _debug_print_payload(title: str, payload: dict[str, Any]) -> None:
    print(f"[DEBUG] {title}: {json.dumps(payload, default=str, ensure_ascii=True)}")


def _mask_secret(value: object) -> str:
    text = str(value or "")
    if not text:
        return "<empty>"
    if len(text) <= 10:
        return f"{text[:2]}...({len(text)})"
    return f"{text[:6]}...{text[-4:]}(len={len(text)})"


def _install_zoho_debug_hooks(client: ZohoClient, *, enabled: bool) -> None:
    if not enabled:
        return

    original_refresh = client._refresh_access_token
    original_request = client._request

    async def traced_refresh(self):
        print(
            "[ZOHO-DEBUG] refresh_start "
            f"org_id={self.organization_id} "
            f"client_id={_mask_secret(self.client_id)} "
            f"refresh_token={_mask_secret(self.refresh_token)}"
        )
        await original_refresh()
        print(
            "[ZOHO-DEBUG] refresh_done "
            f"access_token={_mask_secret(self._access_token)} "
            f"expires_at={self._token_expires_at}"
        )

    async def traced_request(self, method: str, endpoint: str, api: str = "inventory", **kwargs):
        params = dict(kwargs.get("params") or {})
        incoming_org = params.get("organization_id")
        payload_mode = "none"
        payload_keys: list[str] = []
        if "files" in kwargs:
            payload_mode = "files"
            files_payload = kwargs.get("files")
            if isinstance(files_payload, dict):
                payload_keys = list(files_payload.keys())
        elif "json" in kwargs:
            payload_mode = "json"
            json_payload = kwargs.get("json")
            if isinstance(json_payload, dict):
                payload_keys = list(json_payload.keys())
        elif "data" in kwargs:
            payload_mode = "data"
            data_payload = kwargs.get("data")
            if isinstance(data_payload, dict):
                payload_keys = list(data_payload.keys())

        print(
            "[ZOHO-DEBUG] request "
            f"method={method} endpoint={endpoint} api={api} "
            f"org_id_param={incoming_org or '<none>'} org_id_client={self.organization_id} "
            f"token={_mask_secret(self._access_token)} payload_mode={payload_mode} payload_keys={payload_keys}"
        )
        return await original_request(method, endpoint, api=api, **kwargs)

    client._refresh_access_token = MethodType(traced_refresh, client)
    client._request = MethodType(traced_request, client)


def _parse_iso(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except Exception as exc:
        raise ValueError(f"Invalid date '{value}', expected YYYY-MM-DD") from exc


def _to_decimal(value: object, default: str = "0") -> Decimal:
    try:
        text = str(value if value is not None else default).replace("$", "").replace(",", "").strip()
        if not text:
            text = default
        return Decimal(text)
    except Exception:
        return Decimal(default)


def _to_float_money(value: object) -> float:
    return float(_to_decimal(value, default="0"))


def _is_zoho_unauthorized(exc: Exception) -> bool:
    text = str(exc)
    return '"code":57' in text or "not authorized" in text.lower()


def _build_bill_payload(po: PurchaseOrder, variant_zoho_item_by_id: dict[int, str]) -> dict[str, Any]:
    if not po.vendor or not po.vendor.zoho_id:
        raise ValueError("vendor is missing zoho_id")

    line_items: list[dict[str, Any]] = []
    if not po.zoho_id:
        # Standalone fallback when local PO is not linked to Zoho PO.
        for item in po.items or []:
            qty = int(item.quantity or 0)
            if qty <= 0:
                continue

            line: dict[str, Any] = {
                "name": str(item.external_item_name or "Imported Item")[:255],
                "quantity": qty,
                "rate": _to_float_money(item.unit_price),
            }

            variant_id = getattr(item, "variant_id", None)
            zoho_item_id = str(variant_zoho_item_by_id.get(int(variant_id or 0), "") or "").strip()
            if zoho_item_id:
                line["item_id"] = zoho_item_id
            else:
                line["description"] = "Auto-backfill line without mapped Zoho item ID"

            line_items.append(line)

        if not line_items:
            raise ValueError("no billable line items")

    bill_date = po.order_date.isoformat()
    payload: dict[str, Any] = {
        "vendor_id": str(po.vendor.zoho_id),
        "bill_number": po.po_number,
        "reference_number": po.po_number,
        "date": bill_date,
        "due_date": bill_date,
        "payment_terms": PAYMENT_TERMS_DUE_ON_RECEIPT,
        "currency_code": str(po.currency or "USD"),
    }

    if po.zoho_id:
        # Prefer PO-linked bill creation path so the bill is attached to this PO in Zoho.
        payload["purchaseorder_id"] = str(po.zoho_id)
    else:
        payload["line_items"] = line_items

    charge_total = _to_decimal(po.tax_amount, "0") + _to_decimal(po.shipping_amount, "0") + _to_decimal(po.handling_amount, "0")
    if charge_total != Decimal("0"):
        payload["adjustment"] = float(charge_total)
        payload["adjustment_description"] = "Shipping Fee + Tax + Handling Fee"

    if po.notes:
        payload["notes"] = str(po.notes)

    return payload


def _build_payment_payload(po: PurchaseOrder, bill_id: str, amount: float) -> dict[str, Any]:
    if not po.vendor or not po.vendor.zoho_id:
        raise ValueError("vendor is missing zoho_id")
    if amount <= 0:
        raise ValueError("payment amount must be > 0")

    payment_date = po.order_date.isoformat()
    return {
        "vendor_id": str(po.vendor.zoho_id),
        "date": payment_date,
        "payment_mode": "Credit Card",
        "paid_through_account_id": PAID_THROUGH_ACCOUNT_ID_GOODS_IN_TRANSIT,
        "amount": amount,
        "reference_number": po.po_number,
        "description": "Auto-created from eBay purchase-order backfill",
        "bills": [
            {
                "bill_id": bill_id,
                "amount_applied": amount,
            }
        ],
    }


async def _load_local_pos(
    start_date: date,
    end_date: date,
    limit: int | None,
) -> tuple[list[PurchaseOrder], dict[int, str]]:
    async with async_session_factory() as session:
        stmt = (
            select(PurchaseOrder)
            .options(
                selectinload(PurchaseOrder.vendor),
                selectinload(PurchaseOrder.items).options(noload(PurchaseOrderItem.variant)),
            )
            .where(
                PurchaseOrder.source.in_(sorted(EBAY_PO_SOURCES)),
                PurchaseOrder.order_date >= start_date,
                PurchaseOrder.order_date <= end_date,
            )
            .order_by(PurchaseOrder.order_date.asc(), PurchaseOrder.id.asc())
        )
        if limit and limit > 0:
            stmt = stmt.limit(limit)

        pos = (await session.execute(stmt)).scalars().all()

        variant_ids: set[int] = set()
        for po in pos:
            for item in po.items or []:
                if item.variant_id:
                    variant_ids.add(int(item.variant_id))

        variant_zoho_item_by_id: dict[int, str] = {}
        if variant_ids:
            rows = await session.execute(
                select(ProductVariant.id, ProductVariant.zoho_item_id).where(ProductVariant.id.in_(sorted(variant_ids)))
            )
            for variant_id, zoho_item_id in rows.all():
                normalized = str(zoho_item_id or "").strip()
                if normalized:
                    variant_zoho_item_by_id[int(variant_id)] = normalized

        return pos, variant_zoho_item_by_id


async def _list_bills_inventory_fallback(
    client: ZohoClient,
    *,
    start_date: date,
    end_date: date,
    page: int,
    per_page: int,
) -> list[dict[str, Any]]:
    result = await client._request(
        "GET",
        "/bills",
        api="inventory",
        params={
            "date_start": start_date.isoformat(),
            "date_end": end_date.isoformat(),
            "page": page,
            "per_page": per_page,
            "filter_by": "Status.All",
        },
    )
    return result.get("bills", []) or []


async def _load_zoho_bills_by_number(client: ZohoClient, start_date: date, end_date: date) -> dict[str, dict[str, Any]]:
    page = 1
    per_page = 200
    by_number: dict[str, dict[str, Any]] = {}

    while True:
        rows = await _list_bills_inventory_fallback(
            client,
            start_date=start_date,
            end_date=end_date,
            page=page,
            per_page=per_page,
        )
        if not rows:
            break

        for row in rows:
            bill_number = str(row.get("bill_number") or "").strip()
            if bill_number and bill_number not in by_number:
                by_number[bill_number] = row

        if len(rows) < per_page:
            break
        page += 1

    return by_number


async def _create_bill_with_fallback(client: ZohoClient, bill_payload: dict[str, Any]) -> dict[str, Any]:
    result = await client._request(
        "POST",
        "/bills",
        api="inventory",
        data={"JSONString": json.dumps(bill_payload)},
    )
    return result.get("bill", {}) or {}


async def _list_bill_payments_with_fallback(client: ZohoClient, bill_id: str) -> list[dict[str, Any]]:
    result = await client._request(
        "GET",
        "/vendorpayments",
        api="inventory",
        params={
            "bill_id": bill_id,
            "page": 1,
            "per_page": 200,
        },
    )
    return result.get("vendorpayments", []) or result.get("vendor_payments", []) or []


def _resolve_bill_amount(po: PurchaseOrder, bill: dict[str, Any]) -> float:
    bill_total = _to_float_money(bill.get("total"))
    if bill_total > 0:
        return bill_total

    po_total = _to_float_money(po.total_amount)
    if po_total > 0:
        return po_total

    line_total = sum(_to_float_money(item.unit_price) * int(item.quantity or 0) for item in (po.items or []))
    if line_total > 0:
        return line_total

    return 0.0


async def _process_po(
    *,
    po: PurchaseOrder,
    client: ZohoClient,
    bills_by_number: dict[str, dict[str, Any]],
    variant_zoho_item_by_id: dict[int, str],
    apply: bool,
    debug_payloads: bool,
    debug_payload_limit: int,
    stats: Stats,
) -> None:
    stats.scanned += 1

    po_number = str(po.po_number or "").strip()
    if not po_number:
        stats.failed += 1
        stats.failures.append(f"PO id={po.id} skipped: missing po_number")
        return

    try:
        bill_payload = _build_bill_payload(po, variant_zoho_item_by_id)
        stats.eligible += 1
        if debug_payloads and stats.eligible <= debug_payload_limit:
            _debug_print_payload(f"PO {po_number} bill_payload", bill_payload)
    except Exception as exc:
        stats.failed += 1
        stats.failures.append(f"PO {po_number} skipped: {exc}")
        return

    bill = bills_by_number.get(po_number)
    if bill:
        stats.skipped_existing_bill += 1
    else:
        if apply:
            try:
                bill = await _create_bill_with_fallback(client, bill_payload)
                stats.created_bills += 1
            except Exception as exc:
                stats.failed += 1
                stats.failures.append(f"PO {po_number} bill create failed: {exc}")
                return
        else:
            stats.would_create_bills += 1
            stats.would_create_payments += 1
            if debug_payloads and stats.eligible <= debug_payload_limit:
                preview_amount = _to_float_money(po.total_amount)
                payment_preview = {
                    "vendor_id": str(po.vendor.zoho_id),
                    "date": po.order_date.isoformat(),
                    "payment_mode": "Credit Card",
                    "paid_through_account_id": PAID_THROUGH_ACCOUNT_ID_GOODS_IN_TRANSIT,
                    "amount": preview_amount,
                    "reference_number": po.po_number,
                    "description": "Auto-created from eBay purchase-order backfill",
                    "bills": [{"bill_id": "<to-be-created>", "amount_applied": preview_amount}],
                }
                _debug_print_payload(f"PO {po_number} payment_payload_preview", payment_preview)
            return

    bill_id = str((bill or {}).get("bill_id") or "").strip()
    if not bill_id:
        stats.failed += 1
        stats.failures.append(f"PO {po_number} bill resolution failed: missing bill_id")
        return

    try:
        existing_payments = await _list_bill_payments_with_fallback(client, bill_id)
    except Exception as exc:
        stats.failed += 1
        stats.failures.append(f"PO {po_number} payment check failed for bill {bill_id}: {exc}")
        return

    if existing_payments:
        stats.skipped_existing_payment += 1
        return

    amount = _resolve_bill_amount(po, bill)
    if amount <= 0:
        stats.failed += 1
        stats.failures.append(f"PO {po_number} payment skipped: non-positive amount")
        return

    try:
        payment_payload = _build_payment_payload(po, bill_id, amount)
    except Exception as exc:
        stats.failed += 1
        stats.failures.append(f"PO {po_number} payment payload failed: {exc}")
        return

    if apply:
        try:
            await client.create_vendor_payment(payment_payload)
            stats.created_payments += 1
        except Exception as exc:
            stats.failed += 1
            stats.failures.append(f"PO {po_number} payment create failed: {exc}")
    else:
        stats.would_create_payments += 1


async def main() -> None:
    today = date.today()

    parser = argparse.ArgumentParser(description="Backfill Zoho bills/payments for local eBay purchase orders")
    parser.add_argument("--start-date", default="2026-03-01", help="YYYY-MM-DD (default: 2026-03-01)")
    parser.add_argument("--end-date", default=today.isoformat(), help="YYYY-MM-DD (default: today)")
    parser.add_argument("--limit", type=int, default=0, help="Optional cap on number of POs to process")
    parser.add_argument("--apply", action="store_true", help="Execute creates (default is dry-run)")
    parser.add_argument(
        "--skip-zoho-prefetch",
        action="store_true",
        help="Skip Zoho bill prefetch/idempotency lookup (default true for dry-run, false for apply)",
    )
    parser.add_argument(
        "--debug-payloads",
        action="store_true",
        help="Print the first N generated Zoho payloads for debugging",
    )
    parser.add_argument(
        "--debug-payload-limit",
        type=int,
        default=3,
        help="Number of payloads to print when --debug-payloads is set (default: 3)",
    )
    parser.add_argument(
        "--debug-zoho-auth",
        action="store_true",
        help="Trace Zoho token refresh and request auth context (token values are masked)",
    )
    args = parser.parse_args()

    start_date = _parse_iso(args.start_date)
    end_date = _parse_iso(args.end_date)
    if end_date < start_date:
        raise ValueError("end-date must be greater than or equal to start-date")

    limit = args.limit if args.limit and args.limit > 0 else None
    apply = bool(args.apply)
    skip_zoho_prefetch = bool(args.skip_zoho_prefetch) or (not apply)
    debug_payloads = bool(args.debug_payloads)
    debug_payload_limit = max(1, int(args.debug_payload_limit or 1))
    debug_zoho_auth = bool(args.debug_zoho_auth)

    print(f"Window: {start_date.isoformat()} -> {end_date.isoformat()}")
    print(f"Mode: {'APPLY' if apply else 'DRY-RUN'}")
    print(f"Zoho prefetch: {'SKIPPED' if skip_zoho_prefetch else 'ENABLED'}")
    if limit:
        print(f"Limit: {limit}")

    local_pos, variant_zoho_item_by_id = await _load_local_pos(start_date, end_date, limit)
    print(f"Local eBay purchase orders found: {len(local_pos)}")

    if not local_pos:
        print("Nothing to process.")
        return

    client = ZohoClient()
    _install_zoho_debug_hooks(client, enabled=debug_zoho_auth)
    bills_by_number: dict[str, dict[str, Any]] = {}
    if not skip_zoho_prefetch:
        try:
            bills_by_number = await _load_zoho_bills_by_number(client, start_date, end_date)
        except Exception as exc:
            if apply:
                raise
            stats_warning = f"Bill prefetch unavailable in dry-run (continuing without existing-bill checks): {exc}"
            print(stats_warning)
    else:
        print("Skipping Zoho bill prefetch; run with --apply (or remove --skip-zoho-prefetch) for idempotency lookup.")
    print(f"Existing Zoho bills in window: {len(bills_by_number)}")

    stats = Stats()
    for po in local_pos:
        await _process_po(
            po=po,
            client=client,
            bills_by_number=bills_by_number,
            variant_zoho_item_by_id=variant_zoho_item_by_id,
            apply=apply,
            debug_payloads=debug_payloads,
            debug_payload_limit=debug_payload_limit,
            stats=stats,
        )

    print("\nSummary")
    print(f"- scanned: {stats.scanned}")
    print(f"- eligible: {stats.eligible}")
    print(f"- skipped_existing_bill: {stats.skipped_existing_bill}")
    print(f"- skipped_existing_payment: {stats.skipped_existing_payment}")
    print(f"- would_create_bills: {stats.would_create_bills}")
    print(f"- created_bills: {stats.created_bills}")
    print(f"- would_create_payments: {stats.would_create_payments}")
    print(f"- created_payments: {stats.created_payments}")
    print(f"- failed: {stats.failed}")

    if stats.failures:
        print("\nFailures (first 50)")
        for line in stats.failures[:50]:
            print(f"- {line}")


if __name__ == "__main__":
    asyncio.run(main())
