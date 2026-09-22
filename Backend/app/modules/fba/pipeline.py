"""
Pure merge logic for the FBA import — a straight port of the parse + merge
steps in ``FBA/main.py`` (steps 1-3), minus all file I/O and the archive-folder
deduplication (the ERP dedupes on ``(platform, external_order_id)`` at ingest).

``build_merged_rows(all_orders_txt, fulfillment_csv)`` takes the two report
bodies as text and returns ``(fieldnames, rows, stats)`` where each row is a
merged order-line dict keyed like the old ``final_orders_*.csv`` (``order-id``,
``buyer-name``, ``sku``, ``item-price``, …). ``rows_to_csv_text`` serialises
that back so the existing ``_parse_amazon_fba_csv`` can consume it unchanged.
"""
from __future__ import annotations

import csv
import io
import re
from collections import defaultdict
from dataclasses import dataclass, field

# ── Column ordering / field maps (verbatim from FBA/main.py) ─────────────────
FIRST_COLUMNS = [
    "order-id", "buyer-name", "purchase-date", "payment-date", "order-status",
    "buyer-id", "shipment-date", "product-name", "sku", "asin", "quantity",
    "item-price", "item-tax", "ship-city", "ship-state", "ship-postal-code",
]

ALL_ORDER_FIELD_MAP = {
    "amazon-order-id": "order-id",
    "merchant-order-id": "merchant-order-id",
    "purchase-date": "purchase-date",
    "last-updated-date": "last-updated-date",
    "order-status": "order-status",
    "fulfillment-channel": "fulfillment-channel",
    "sales-channel": "sales-channel",
    "order-channel": "order-channel",
    "url": "url",
    "ship-service-level": "ship-service-level",
    "product-name": "product-name",
    "sku": "sku",
    "asin": "asin",
    "item-status": "item-status",
    "quantity": "quantity",
    "currency": "currency",
    "item-price": "item-price",
    "item-tax": "item-tax",
    "shipping-price": "shipping-price",
    "shipping-tax": "shipping-tax",
    "gift-wrap-price": "gift-wrap-price",
    "gift-wrap-tax": "gift-wrap-tax",
    "item-promotion-discount": "item-promotion-discount",
    "ship-promotion-discount": "ship-promotion-discount",
    "ship-city": "ship-city",
    "ship-state": "ship-state",
    "ship-postal-code": "ship-postal-code",
    "ship-country": "ship-country",
    "promotion-ids": "promotion-ids",
    "cpf": "cpf",
    "is-business-order": "is-business-order",
    "purchase-order-number": "purchase-order-number",
    "price-designation": "price-designation",
    "signature-confirmation-recommended": "signature-confirmation-recommended",
    "buyer-identification-number": "buyer-identification-number",
    "buyer-identification-type": "buyer-identification-type",
    "order-item-id": "order-item-id",
}

SHIPMENT_FIELD_MAP = {
    "amazon-order-id": "order-id",
    "merchant-order-id": "merchant-order-id",
    "shipment-id": "shipment-id",
    "shipment-item-id": "shipment-item-id",
    "amazon-order-item-id": "amazon-order-item-id",
    "merchant-order-item-id": "merchant-order-item-id",
    "purchase-date": "purchase-date",
    "payments-date": "payment-date",
    "shipment-date": "shipment-date",
    "reporting-date": "reporting-date",
    "buyer-email": "buyer-email",
    "buyer-name": "buyer-name",
    "buyer-phone-number": "buyer-phone-number",
    "merchant-sku": "sku",
    "title": "product-name",
    "shipped-quantity": "quantity",
    "currency": "currency",
    "item-price": "item-price",
    "item-tax": "item-tax",
    "shipping-price": "shipping-price",
    "shipping-tax": "shipping-tax",
    "gift-wrap-price": "gift-wrap-price",
    "gift-wrap-tax": "gift-wrap-tax",
    "ship-service-level": "ship-service-level",
    "recipient-name": "recipient-name",
    "shipping-address-1": "shipping-address-1",
    "shipping-address-2": "shipping-address-2",
    "shipping-address-3": "shipping-address-3",
    "shipping-city": "ship-city",
    "shipping-state": "ship-state",
    "shipping-postal-code": "ship-postal-code",
    "shipping-country-code": "ship-country",
    "shipping-phone-number": "shipping-phone-number",
    "billing-address-1": "billing-address-1",
    "billing-address-2": "billing-address-2",
    "billing-address-3": "billing-address-3",
    "billing-city": "billing-city",
    "billing-state": "billing-state",
    "bill-postal-code": "bill-postal-code",
    "bill-country": "bill-country",
    "item-promo-discount": "item-promotion-discount",
    "shipment-promo-discount": "ship-promotion-discount",
    "carrier": "carrier",
    "tracking-number": "tracking-number",
    "estimated-arrival-date": "estimated-arrival-date",
    "fc": "fc",
    "fulfillment-channel": "shipment-fulfillment-channel",
    "sales-channel": "sales-channel",
}


class PipelineError(ValueError):
    """Raised when an input file is empty or missing required columns."""


@dataclass
class PipelineStats:
    all_order_rows: int = 0
    fba_order_rows: int = 0
    shipment_rows: int = 0
    merged_rows: int = 0
    rows_missing_buyer_name: int = 0
    warnings: list[str] = field(default_factory=list)


# ── Helpers (verbatim from FBA/main.py) ─────────────────────────────────────
def slugify_header(header: str) -> str:
    header = header.strip().lstrip("﻿")
    header = re.sub(r"[^0-9A-Za-z]+", "-", header)
    return re.sub(r"-{2,}", "-", header).strip("-").lower()


def clean_value(value: str) -> str:
    return value.strip() if value else ""


def value_key(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


def values_match(left: str, right: str) -> bool:
    if not left or not right:
        return False
    return value_key(left) == value_key(right)


def filter_all_order_row(row: dict[str, str]) -> bool:
    fulfillment = row.get("fulfillment-channel", "").casefold()
    status = row.get("order-status", "").casefold()
    return fulfillment == "amazon" and (status.startswith("shipping") or status.startswith("shipped"))


def build_shipment_index(rows: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    index: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        order_id = row.get("amazon-order-id", "")
        if order_id:
            index[order_id].append(row)
    return index


def pick_shipment_matches(
    all_order_row: dict[str, str], shipment_index: dict[str, list[dict[str, str]]]
) -> list[dict[str, str] | None]:
    order_id = all_order_row.get("merchant-order-id", "")
    matches = shipment_index.get(order_id, [])
    if not matches:
        return [None]
    if len(matches) == 1:
        return matches

    order_item_id = all_order_row.get("order-item-id", "")
    if order_item_id:
        item_matches = [
            match for match in matches
            if match.get("amazon-order-item-id", "") == order_item_id
        ]
        if item_matches:
            matches = item_matches
            if len(matches) == 1:
                return matches

    sku = all_order_row.get("sku", "")
    if sku:
        sku_matches = [match for match in matches if match.get("merchant-sku", "") == sku]
        if sku_matches:
            return sku_matches

    return matches


def assign_field(target: dict[str, str], key: str, value: str, fallback_key: str | None = None) -> None:
    if not value:
        return
    existing = target.get(key, "")
    if not existing:
        target[key] = value
        return
    if values_match(existing, value):
        return
    if fallback_key and fallback_key != key and not target.get(fallback_key):
        target[fallback_key] = value


def merge_rows(all_order_row: dict[str, str], shipment_row: dict[str, str] | None) -> dict[str, str]:
    merged: dict[str, str] = {}
    for raw_key, value in all_order_row.items():
        output_key = ALL_ORDER_FIELD_MAP.get(raw_key, raw_key)
        assign_field(merged, output_key, value)

    if shipment_row:
        for raw_key, value in shipment_row.items():
            output_key = SHIPMENT_FIELD_MAP.get(raw_key, raw_key)
            fallback_key = None
            if output_key in merged and raw_key not in {"fulfillment-channel"}:
                fallback_key = f"shipment-{output_key}"
            assign_field(merged, output_key, value, fallback_key=fallback_key)

    buyer_email = merged.get("buyer-email", "")
    merged["buyer-id"] = buyer_email.split("@", 1)[0] if buyer_email else ""
    return merged


def ordered_fieldnames(rows: list[dict[str, str]]) -> list[str]:
    seen = set(FIRST_COLUMNS)
    ordered = list(FIRST_COLUMNS)
    for row in rows:
        for key in row:
            if key not in seen:
                ordered.append(key)
                seen.add(key)
    return ordered


# ── Text-based input parsing ────────────────────────────────────────────────
def _parse_all_orders_txt(text: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    if not reader.fieldnames:
        raise PipelineError("All-Orders .txt file is empty.")
    slugged = {slugify_header(name) for name in reader.fieldnames if name}
    if "amazon-order-id" not in slugged:
        raise PipelineError(
            "All-Orders .txt is missing the 'amazon-order-id' column — "
            "is this the Flat File All Orders report?"
        )
    rows = []
    for raw in reader:
        rows.append(
            {slugify_header(k): clean_value(v) for k, v in raw.items() if k}
        )
    return rows


def _parse_fulfillment_csv(text: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise PipelineError("Fulfilment .csv file is empty.")
    slugged = {slugify_header(name) for name in reader.fieldnames if name}
    if "amazon-order-id" not in slugged:
        raise PipelineError(
            "Fulfilment .csv is missing the 'Amazon Order Id' column — "
            "is this the Amazon Fulfilled Shipments report (CSV format)?"
        )
    rows = []
    for raw in reader:
        rows.append(
            {slugify_header(k): clean_value(v) for k, v in raw.items() if k is not None}
        )
    return rows


# ── Public entry point ─────────────────────────────────────────────────────
def build_merged_rows(
    all_orders_txt: str, fulfillment_csv: str
) -> tuple[list[str], list[dict[str, str]], PipelineStats]:
    """Port of FBA/main.py steps 1-3. No dedupe, no scraping, no file I/O."""
    stats = PipelineStats()

    all_orders = _parse_all_orders_txt(all_orders_txt)
    stats.all_order_rows = len(all_orders)

    filtered_all_orders = [row for row in all_orders if filter_all_order_row(row)]
    stats.fba_order_rows = len(filtered_all_orders)
    if not filtered_all_orders:
        stats.warnings.append(
            "No Amazon-fulfilled, shipped/shipping rows found in the All-Orders "
            "report — nothing to import."
        )

    shipment_rows = _parse_fulfillment_csv(fulfillment_csv)
    stats.shipment_rows = len(shipment_rows)
    shipment_index = build_shipment_index(shipment_rows)

    merged_rows: list[dict[str, str]] = []
    for all_order_row in filtered_all_orders:
        for shipment_row in pick_shipment_matches(all_order_row, shipment_index):
            merged_rows.append(merge_rows(all_order_row, shipment_row))

    stats.merged_rows = len(merged_rows)
    stats.rows_missing_buyer_name = sum(
        1 for r in merged_rows if not r.get("buyer-name") and r.get("order-id")
    )

    fieldnames = ordered_fieldnames(merged_rows)
    # buyer-name at index 1, matching FBA/main.py step 6.
    if "buyer-name" in fieldnames:
        fieldnames.remove("buyer-name")
        if "order-id" in fieldnames:
            fieldnames.insert(fieldnames.index("order-id") + 1, "buyer-name")
        else:
            fieldnames.insert(1, "buyer-name")

    return fieldnames, merged_rows, stats


def rows_to_csv_text(fieldnames: list[str], rows: list[dict[str, str]]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({name: row.get(name, "") for name in fieldnames})
    return buf.getvalue()


# ── Reporting-period hint (port of FBA/get_input.py pick_option) ────────────
# The Seller Central "Event date" dropdown offers fixed "last N days" options.
# Amazon currently exposes 7 / 15 / 30 / 60 as the flat-file report windows.
_PERIOD_OPTIONS = (7, 15, 30, 60)


def pick_period_days(days_needed: int) -> int:
    """Smallest 'last N days' option that covers ``days_needed`` (else the widest)."""
    for option in _PERIOD_OPTIONS:
        if option >= days_needed:
            return option
    return _PERIOD_OPTIONS[-1]
