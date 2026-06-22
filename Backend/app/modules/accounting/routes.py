"""Accounting module API routes."""

import csv
import io
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, require_roles
from app.core.database import get_db
from app.models import UserRole
from app.models.entities import Customer, PlatformListing, ProductVariant
from app.models.purchasing import PurchaseOrder, PurchaseOrderItem, Vendor
from app.modules.orders.models import Order, OrderItem
from app.modules.accounting.bank_convert_utils import BANK_CONVERT_PARSERS


router = APIRouter(
    prefix="/accounting",
    tags=["Accounting"],
    dependencies=[Depends(require_roles(UserRole.ADMIN, UserRole.ACCOUNTANT))],
)

GroupByType = Literal["sku", "week", "month", "quarter", "year", "source", "vendor"]
SalesGroupByType = Literal["sku", "week", "month", "quarter", "year", "source", "customer"]
OrderByType = Literal["total_price", "quantity", "sku", "source", "date"]


def _group_value(group_by: GroupByType | SalesGroupByType, order_date: date | None, sku: str | None, source: str | None, counterparty: str | None) -> str:
    if group_by == "sku":
        return (sku or "UNMATCHED").strip() or "UNMATCHED"
    if group_by == "source":
        return (source or "UNKNOWN").strip() or "UNKNOWN"
    if group_by in ("vendor", "customer"):
        return (counterparty or "UNKNOWN").strip() or "UNKNOWN"
    if not order_date:
        return "UNKNOWN"
    if group_by == "week":
        iso_year, iso_week, _ = order_date.isocalendar()
        return f"{iso_year}-W{iso_week:02d}"
    if group_by == "month":
        return order_date.strftime("%Y-%m")
    if group_by == "quarter":
        quarter = ((order_date.month - 1) // 3) + 1
        return f"{order_date.year}-Q{quarter}"
    return str(order_date.year)


def _xlsx_bytes(rows: list[dict[str, object]], headers: list[str]) -> bytes:
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    sheet_rows: list[str] = []

    def _cell_xml(value: object) -> str:
        text = "" if value is None else str(value)
        return f'<c t="inlineStr"><is><t>{escape(text)}</t></is></c>'

    header_cells = "".join(_cell_xml(header) for header in headers)
    sheet_rows.append(f'<row r="1">{header_cells}</row>')
    for idx, row in enumerate(rows, start=2):
        body_cells = "".join(_cell_xml(row.get(header)) for header in headers)
        sheet_rows.append(f'<row r="{idx}">{body_cells}</row>')

    worksheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        "<sheetData>"
        f"{''.join(sheet_rows)}"
        "</sheetData>"
        "</worksheet>"
    )

    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
        '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
        '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
        "</Relationships>"
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Report" sheetId="1" r:id="rId1"/></sheets>'
        "</workbook>"
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        "</Relationships>"
    )
    core = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        "<dc:creator>USAV Inventory</dc:creator>"
        "<cp:lastModifiedBy>USAV Inventory</cp:lastModifiedBy>"
        f'<dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>'
        f'<dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified>'
        "</cp:coreProperties>"
    )
    app = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
        'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
        "<Application>USAV Inventory</Application>"
        "</Properties>"
    )

    output = io.BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("xl/workbook.xml", workbook)
        zf.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        zf.writestr("xl/worksheets/sheet1.xml", worksheet_xml)
        zf.writestr("docProps/core.xml", core)
        zf.writestr("docProps/app.xml", app)
    output.seek(0)
    return output.getvalue()


async def _build_purchase_order_report(
    db: AsyncSession,
    start_date: date,
    end_date: date,
    group_by: GroupByType,
    item_filter: list[str] | None = None,
    source_filter: list[str] | None = None,
    vendor_filter: list[str] | None = None,
    po_status_filter: list[str] | None = None,
    order_by: OrderByType = "date",
    export_full: bool = False,
) -> list[dict[str, object]]:
    stmt = (
        select(
            PurchaseOrder.order_date.label("order_date"),
            PurchaseOrder.po_number.label("order_number"),
            PurchaseOrder.deliver_status.label("po_status"),
            PurchaseOrderItem.external_item_name.label("item"),
            ProductVariant.full_sku.label("sku"),
            ProductVariant.variant_name.label("inventory_name"),
            PurchaseOrder.source.label("source"),
            PurchaseOrderItem.quantity.label("quantity"),
            PurchaseOrderItem.total_price.label("item_total_price"),
            PurchaseOrder.tax_amount.label("tax_amount"),
            PurchaseOrder.shipping_amount.label("shipping_amount"),
            PurchaseOrder.handling_amount.label("handling_amount"),
            Vendor.name.label("vendor"),
        )
        .join(PurchaseOrderItem, PurchaseOrderItem.purchase_order_id == PurchaseOrder.id)
        .join(Vendor, Vendor.id == PurchaseOrder.vendor_id)
        .outerjoin(ProductVariant, ProductVariant.id == PurchaseOrderItem.variant_id)
        .where(and_(PurchaseOrder.order_date >= start_date, PurchaseOrder.order_date <= end_date))
    )
    if item_filter:
        stmt = stmt.where(
            or_(
                *[
                    or_(
                        ProductVariant.full_sku.ilike(f"%{token}%"),
                        PurchaseOrderItem.external_item_name.ilike(f"%{token}%"),
                    )
                    for token in item_filter
                ]
            )
        )
    if source_filter:
        stmt = stmt.where(PurchaseOrder.source.in_(source_filter))
    if vendor_filter:
        stmt = stmt.where(or_(*[Vendor.name.ilike(f"%{token}%") for token in vendor_filter]))
    if po_status_filter:
        stmt = stmt.where(PurchaseOrder.deliver_status.in_(po_status_filter))
    rows = (await db.execute(stmt)).mappings().all()

    if export_full:
        export_rows = list(rows)
        if order_by == "total_price":
            export_rows.sort(key=lambda row: Decimal(row["item_total_price"] or 0), reverse=True)
        elif order_by == "quantity":
            export_rows.sort(key=lambda row: int(row["quantity"] or 0), reverse=True)
        elif order_by == "sku":
            export_rows.sort(key=lambda row: str(row["sku"] or "").lower())
        elif order_by == "source":
            export_rows.sort(key=lambda row: str(row["source"] or "").lower())
        else:
            export_rows.sort(
                key=lambda row: row["order_date"] if isinstance(row["order_date"], date) else date.min,
                reverse=True,
            )

        report_rows: list[dict[str, object]] = []
        for row in export_rows:
            report_rows.append(
                {
                    "group": "",
                    "order_date": row["order_date"].isoformat() if row["order_date"] else "",
                    "order_number": row["order_number"],
                    "po_status": row["po_status"].value if row["po_status"] is not None and hasattr(row["po_status"], "value") else str(row["po_status"] or ""),
                    "item": row["item"],
                    "sku": row["sku"],
                    "inventory_name": row["inventory_name"],
                    "source": row["source"],
                    "quantity": row["quantity"],
                    "total_price": str(Decimal(row["item_total_price"] or 0).quantize(Decimal("0.01"))),
                    "tax": str(Decimal(row["tax_amount"] or 0).quantize(Decimal("0.01"))),
                    "shipping": str(Decimal(row["shipping_amount"] or 0).quantize(Decimal("0.01"))),
                    "handling": str(Decimal(row["handling_amount"] or 0).quantize(Decimal("0.01"))),
                    "vendor": row["vendor"],
                }
            )
        return report_rows

    grouped: dict[str, dict[str, object]] = {}
    for row in rows:
        key = _group_value(
            group_by=group_by,
            order_date=row["order_date"],
            sku=row["sku"],
            source=row["source"],
            counterparty=row["vendor"],
        )
        entry = grouped.setdefault(
            key,
            {
                "group": key,
                "order_date": row["order_date"],
                "order_number": row["order_number"] if group_by == "sku" else "",
                "item": row["item"] if group_by == "sku" else "",
                "sku": row["sku"] if group_by == "sku" else "",
                "source": row["source"] if group_by == "source" else "",
                "vendor": row["vendor"] if group_by == "vendor" else "",
                "quantity": 0,
                "total_price": Decimal("0"),
                "tax": Decimal("0"),
                "shipping": Decimal("0"),
                "handling": Decimal("0"),
            },
        )
        entry["quantity"] = int(entry["quantity"]) + int(row["quantity"] or 0)
        entry["total_price"] = Decimal(entry["total_price"]) + Decimal(row["item_total_price"] or 0)
        entry["tax"] = Decimal(entry["tax"]) + Decimal(row["tax_amount"] or 0)
        entry["shipping"] = Decimal(entry["shipping"]) + Decimal(row["shipping_amount"] or 0)
        entry["handling"] = Decimal(entry["handling"]) + Decimal(row["handling_amount"] or 0)

    grouped_values = list(grouped.values())
    if order_by == "total_price":
        grouped_values.sort(key=lambda value: Decimal(value["total_price"]), reverse=True)
    elif order_by == "quantity":
        grouped_values.sort(key=lambda value: int(value["quantity"]), reverse=True)
    elif order_by == "sku":
        grouped_values.sort(key=lambda value: str(value["sku"] or "").lower())
    elif order_by == "source":
        grouped_values.sort(key=lambda value: str(value["source"] or "").lower())
    else:
        grouped_values.sort(
            key=lambda value: value["order_date"] if isinstance(value["order_date"], date) else date.min,
            reverse=True,
        )

    report_rows: list[dict[str, object]] = []
    for value in grouped_values:
        report_rows.append(
            {
                "group": value["group"],
                "order_date": value["order_date"].isoformat() if value["order_date"] else "",
                "order_number": value["order_number"],
                "item": value["item"],
                "sku": value["sku"],
                "source": value["source"],
                "quantity": value["quantity"],
                "total_price": str(Decimal(value["total_price"]).quantize(Decimal("0.01"))),
                "tax": str(Decimal(value["tax"]).quantize(Decimal("0.01"))),
                "shipping": str(Decimal(value["shipping"]).quantize(Decimal("0.01"))),
                "handling": str(Decimal(value["handling"]).quantize(Decimal("0.01"))),
                "vendor": value["vendor"],
            }
        )
    return report_rows


async def _build_purchase_order_filter_options(
    db: AsyncSession,
    start_date: date,
    end_date: date,
) -> dict[str, object]:
    stmt = (
        select(
            ProductVariant.full_sku.label("sku"),
            PurchaseOrder.source.label("source"),
            Vendor.name.label("vendor"),
            PurchaseOrderItem.external_item_name.label("name"),
            PurchaseOrder.deliver_status.label("po_status"),
        )
        .join(PurchaseOrderItem, PurchaseOrderItem.purchase_order_id == PurchaseOrder.id)
        .join(Vendor, Vendor.id == PurchaseOrder.vendor_id)
        .outerjoin(ProductVariant, ProductVariant.id == PurchaseOrderItem.variant_id)
        .where(and_(PurchaseOrder.order_date >= start_date, PurchaseOrder.order_date <= end_date))
    )
    rows = (await db.execute(stmt)).mappings().all()

    item_options: dict[str, str] = {}
    for row in rows:
        sku = (row["sku"] or "").strip()
        name = (row["name"] or "").strip()
        label = ""
        value = ""
        if sku and name:
            label = f"{sku} - {name}"
            value = sku
        elif sku:
            label = sku
            value = sku
        elif name:
            label = name
            value = name
        if value and value not in item_options:
            item_options[value] = label
    source_values = sorted({(row["source"] or "").strip() for row in rows if (row["source"] or "").strip()})
    vendor_values = sorted({(row["vendor"] or "").strip() for row in rows if (row["vendor"] or "").strip()})
    po_status_values = sorted(
        {
            (row["po_status"].value if row["po_status"] is not None and hasattr(row["po_status"], "value") else str(row["po_status"] or "").strip())
            for row in rows
            if row["po_status"] is not None and str(row["po_status"]).strip()
        }
    )
    return {
        "item_options": [{"value": value, "label": label} for value, label in sorted(item_options.items(), key=lambda item: item[1].lower())],
        "source_options": source_values,
        "vendor_options": vendor_values,
        "po_status_options": po_status_values,
    }


async def _build_sales_order_report(
    db: AsyncSession,
    start_date: date,
    end_date: date,
    group_by: SalesGroupByType,
    item_filter: list[str] | None = None,
    source_filter: list[str] | None = None,
    customer_filter: list[str] | None = None,
    order_by: OrderByType = "date",
    export_full: bool = False,
) -> list[dict[str, object]]:
    stmt = (
        select(
            Order.ordered_at.label("order_at"),
            Order.external_order_number.label("order_number"),
            Order.external_order_id.label("order_id"),
            OrderItem.item_name.label("item"),
            ProductVariant.full_sku.label("sku"),
            ProductVariant.variant_name.label("inventory_name"),
            PlatformListing.external_ref_id.label("listing_external_ref"),
            OrderItem.external_item_id.label("external_item_id"),
            OrderItem.external_sku.label("external_sku"),
            Order.source.label("source"),
            OrderItem.quantity.label("quantity"),
            OrderItem.total_price.label("item_total_price"),
            Order.tax_amount.label("tax_amount"),
            Order.shipping_amount.label("shipping_amount"),
            Customer.name.label("customer"),
            Order.tracking_number.label("tracking_number"),
        )
        .join(OrderItem, OrderItem.order_id == Order.id)
        .outerjoin(ProductVariant, ProductVariant.id == OrderItem.variant_id)
        .outerjoin(PlatformListing, PlatformListing.id == OrderItem.platform_listing_id)
        .outerjoin(Customer, Customer.id == Order.customer_id)
        .where(Order.ordered_at.is_not(None))
        .where(and_(func.date(Order.ordered_at) >= start_date, func.date(Order.ordered_at) <= end_date))
    )
    if item_filter:
        stmt = stmt.where(
            or_(
                *[
                    or_(
                        ProductVariant.full_sku.ilike(f"%{token}%"),
                        OrderItem.external_sku.ilike(f"%{token}%"),
                        OrderItem.item_name.ilike(f"%{token}%"),
                    )
                    for token in item_filter
                ]
            )
            )
    if source_filter:
        stmt = stmt.where(Order.source.in_(source_filter))
    if customer_filter:
        stmt = stmt.where(or_(*[Customer.name.ilike(f"%{token}%") for token in customer_filter]))
    rows = (await db.execute(stmt)).mappings().all()

    if export_full:
        export_rows = list(rows)
        if order_by == "total_price":
            export_rows.sort(key=lambda row: Decimal(row["item_total_price"] or 0), reverse=True)
        elif order_by == "quantity":
            export_rows.sort(key=lambda row: int(row["quantity"] or 0), reverse=True)
        elif order_by == "sku":
            export_rows.sort(
                key=lambda row: str(
                    row["sku"]
                    or row["listing_external_ref"]
                    or row["external_item_id"]
                    or row["external_sku"]
                    or ""
                ).lower()
            )
        elif order_by == "source":
            export_rows.sort(key=lambda row: str(row["source"] or "").lower())
        else:
            export_rows.sort(
                key=lambda row: row["order_at"] if isinstance(row["order_at"], datetime) else datetime.min,
                reverse=True,
            )

        report_rows: list[dict[str, object]] = []
        for row in export_rows:
            ordered_at = row["order_at"]
            order_date = ordered_at.date() if isinstance(ordered_at, datetime) else None
            display_order_number = (row["order_number"] or row["order_id"] or "").strip()
            inventory_sku = (row["sku"] or "").strip()
            platform_sku = (
                row["listing_external_ref"]
                or row["external_item_id"]
                or row["external_sku"]
                or ""
            ).strip()
            report_rows.append(
                {
                    "group": "",
                    "order_date": order_date.isoformat() if order_date else "",
                    "order_number": display_order_number,
                    "item": row["item"],
                    "inventory_name": row["inventory_name"],
                    "inventory_sku": inventory_sku,
                    "platform_sku": platform_sku,
                    "source": row["source"],
                    "quantity": row["quantity"],
                    "total_price": str(Decimal(row["item_total_price"] or 0).quantize(Decimal("0.01"))),
                    "tax": str(Decimal(row["tax_amount"] or 0).quantize(Decimal("0.01"))),
                    "shipping": str(Decimal(row["shipping_amount"] or 0).quantize(Decimal("0.01"))),
                    "handling": str(Decimal("0").quantize(Decimal("0.01"))),
                    "customer": row["customer"],
                    "tracking_number": row["tracking_number"] or "",
                }
            )
        return report_rows

    grouped: dict[str, dict[str, object]] = {}
    for row in rows:
        ordered_at = row["order_at"]
        order_date = ordered_at.date() if isinstance(ordered_at, datetime) else None
        display_sku = (row["sku"] or row["external_sku"] or "").strip()
        display_order_number = (row["order_number"] or row["order_id"] or "").strip()
        key = _group_value(
            group_by=group_by,
            order_date=order_date,
            sku=display_sku,
            source=row["source"],
            counterparty=row["customer"],
        )
        entry = grouped.setdefault(
            key,
            {
                "group": key,
                "order_date": order_date,
                "order_number": display_order_number if group_by == "sku" else "",
                "item": row["item"] if group_by == "sku" else "",
                "sku": display_sku if group_by == "sku" else "",
                "source": row["source"] if group_by == "source" else "",
                "customer": row["customer"] if group_by == "customer" else "",
                "quantity": 0,
                "total_price": Decimal("0"),
                "tax": Decimal("0"),
                "shipping": Decimal("0"),
                "handling": Decimal("0"),
            },
        )
        entry["quantity"] = int(entry["quantity"]) + int(row["quantity"] or 0)
        entry["total_price"] = Decimal(entry["total_price"]) + Decimal(row["item_total_price"] or 0)
        entry["tax"] = Decimal(entry["tax"]) + Decimal(row["tax_amount"] or 0)
        entry["shipping"] = Decimal(entry["shipping"]) + Decimal(row["shipping_amount"] or 0)

    grouped_values = list(grouped.values())
    if order_by == "total_price":
        grouped_values.sort(key=lambda value: Decimal(value["total_price"]), reverse=True)
    elif order_by == "quantity":
        grouped_values.sort(key=lambda value: int(value["quantity"]), reverse=True)
    elif order_by == "sku":
        grouped_values.sort(key=lambda value: str(value["sku"] or "").lower())
    elif order_by == "source":
        grouped_values.sort(key=lambda value: str(value["source"] or "").lower())
    else:
        grouped_values.sort(
            key=lambda value: value["order_date"] if isinstance(value["order_date"], date) else date.min,
            reverse=True,
        )

    report_rows: list[dict[str, object]] = []
    for value in grouped_values:
        report_rows.append(
            {
                "group": value["group"],
                "order_date": value["order_date"].isoformat() if value["order_date"] else "",
                "order_number": value["order_number"],
                "item": value["item"],
                "sku": value["sku"],
                "source": value["source"],
                "quantity": value["quantity"],
                "total_price": str(Decimal(value["total_price"]).quantize(Decimal("0.01"))),
                "tax": str(Decimal(value["tax"]).quantize(Decimal("0.01"))),
                "shipping": str(Decimal(value["shipping"]).quantize(Decimal("0.01"))),
                "handling": str(Decimal(value["handling"]).quantize(Decimal("0.01"))),
                "customer": value["customer"],
            }
        )
    return report_rows


async def _build_sales_order_filter_options(
    db: AsyncSession,
    start_date: date,
    end_date: date,
) -> dict[str, object]:
    stmt = (
        select(
            ProductVariant.full_sku.label("sku"),
            OrderItem.external_sku.label("external_sku"),
            Order.source.label("source"),
            Customer.name.label("customer"),
            OrderItem.item_name.label("name"),
        )
        .join(OrderItem, OrderItem.order_id == Order.id)
        .outerjoin(ProductVariant, ProductVariant.id == OrderItem.variant_id)
        .outerjoin(Customer, Customer.id == Order.customer_id)
        .where(Order.ordered_at.is_not(None))
        .where(and_(func.date(Order.ordered_at) >= start_date, func.date(Order.ordered_at) <= end_date))
    )
    rows = (await db.execute(stmt)).mappings().all()

    item_options: dict[str, str] = {}
    for row in rows:
        sku = (row["sku"] or row["external_sku"] or "").strip()
        name = (row["name"] or "").strip()
        label = ""
        value = ""
        if sku and name:
            label = f"{sku} - {name}"
            value = sku
        elif sku:
            label = sku
            value = sku
        elif name:
            label = name
            value = name
        if value and value not in item_options:
            item_options[value] = label
    source_values = sorted({(row["source"] or "").strip() for row in rows if (row["source"] or "").strip()})
    customer_values = sorted({(row["customer"] or "").strip() for row in rows if (row["customer"] or "").strip()})
    return {
        "item_options": [{"value": value, "label": label} for value, label in sorted(item_options.items(), key=lambda item: item[1].lower())],
        "source_options": source_values,
        "customer_options": customer_values,
    }


def _clean_filters(values: list[str] | None) -> list[str] | None:
    if not values:
        return None
    cleaned = [value.strip() for value in values if value and value.strip()]
    return cleaned or None


@router.get("/reports")
async def get_reports_stub(_: CurrentUser):
    """Phase 1 scaffold endpoint for accounting reports."""
    return {"message": "Report module connected"}


@router.get("/reports/purchase-orders")
async def get_purchase_order_reports(
    _: CurrentUser,
    start_date: date = Query(...),
    end_date: date = Query(...),
    order_by: OrderByType = Query("date"),
    group_by: GroupByType = Query("month"),
    item: list[str] | None = Query(default=None),
    source: list[str] | None = Query(default=None),
    vendor: list[str] | None = Query(default=None),
    po_status: list[str] | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    if end_date < start_date:
        return {"rows": [], "message": "end_date must be on or after start_date"}
    rows = await _build_purchase_order_report(
        db,
        start_date=start_date,
        end_date=end_date,
        order_by=order_by,
        group_by=group_by,
        item_filter=_clean_filters(item),
        source_filter=_clean_filters(source),
        vendor_filter=_clean_filters(vendor),
        po_status_filter=_clean_filters(po_status),
    )
    return {"rows": rows}


@router.get("/reports/purchase-orders/export")
async def export_purchase_order_reports(
    _: CurrentUser,
    start_date: date = Query(...),
    end_date: date = Query(...),
    order_by: OrderByType = Query("date"),
    group_by: GroupByType = Query("month"),
    item: list[str] | None = Query(default=None),
    source: list[str] | None = Query(default=None),
    vendor: list[str] | None = Query(default=None),
    po_status: list[str] | None = Query(default=None),
    file_type: Literal["csv", "xlsx"] = Query("csv"),
    export_full: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    if end_date < start_date:
        end_date = start_date
    rows = await _build_purchase_order_report(
        db,
        start_date=start_date,
        end_date=end_date,
        order_by=order_by,
        group_by=group_by,
        item_filter=_clean_filters(item),
        source_filter=_clean_filters(source),
        vendor_filter=_clean_filters(vendor),
        po_status_filter=_clean_filters(po_status),
        export_full=export_full,
    )
    headers = ["group", "order_date", "order_number", "item", "sku", "source", "quantity", "total_price", "tax", "shipping", "handling", "vendor"]
    if export_full:
        headers = [
            "group",
            "order_date",
            "order_number",
            "po_status",
            "item",
            "sku",
            "inventory_name",
            "source",
            "quantity",
            "total_price",
            "tax",
            "shipping",
            "handling",
            "vendor",
        ]
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    if file_type == "csv":
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
        filename = f"purchase_order_report_{'full' if export_full else group_by}_{stamp}.csv"
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    xlsx_content = _xlsx_bytes(rows=rows, headers=headers)
    filename = f"purchase_order_report_{'full' if export_full else group_by}_{stamp}.xlsx"
    return StreamingResponse(
        io.BytesIO(xlsx_content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/reports/purchase-orders/filter-options")
async def get_purchase_order_report_filter_options(
    _: CurrentUser,
    start_date: date = Query(...),
    end_date: date = Query(...),
    db: AsyncSession = Depends(get_db),
):
    if end_date < start_date:
        return {"item_options": [], "source_options": [], "vendor_options": [], "po_status_options": []}
    return await _build_purchase_order_filter_options(db, start_date=start_date, end_date=end_date)


@router.get("/reports/sales-orders")
async def get_sales_order_reports(
    _: CurrentUser,
    start_date: date = Query(...),
    end_date: date = Query(...),
    order_by: OrderByType = Query("date"),
    group_by: SalesGroupByType = Query("month"),
    item: list[str] | None = Query(default=None),
    source: list[str] | None = Query(default=None),
    customer: list[str] | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    if end_date < start_date:
        return {"rows": [], "message": "end_date must be on or after start_date"}
    rows = await _build_sales_order_report(
        db,
        start_date=start_date,
        end_date=end_date,
        order_by=order_by,
        group_by=group_by,
        item_filter=_clean_filters(item),
        source_filter=_clean_filters(source),
        customer_filter=_clean_filters(customer),
    )
    return {"rows": rows}


@router.get("/reports/sales-orders/export")
async def export_sales_order_reports(
    _: CurrentUser,
    start_date: date = Query(...),
    end_date: date = Query(...),
    order_by: OrderByType = Query("date"),
    group_by: SalesGroupByType = Query("month"),
    item: list[str] | None = Query(default=None),
    source: list[str] | None = Query(default=None),
    customer: list[str] | None = Query(default=None),
    file_type: Literal["csv", "xlsx"] = Query("csv"),
    export_full: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    if end_date < start_date:
        end_date = start_date
    rows = await _build_sales_order_report(
        db,
        start_date=start_date,
        end_date=end_date,
        order_by=order_by,
        group_by=group_by,
        item_filter=_clean_filters(item),
        source_filter=_clean_filters(source),
        customer_filter=_clean_filters(customer),
        export_full=export_full,
    )
    headers = ["group", "order_date", "order_number", "item", "sku", "source", "quantity", "total_price", "tax", "shipping", "handling", "customer"]
    if export_full:
        headers = [
            "group",
            "order_date",
            "order_number",
            "item",
            "inventory_name",
            "inventory_sku",
            "platform_sku",
            "source",
            "quantity",
            "total_price",
            "tax",
            "shipping",
            "handling",
            "customer",
            "tracking_number",
        ]
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    if file_type == "csv":
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
        filename = f"sales_order_report_{'full' if export_full else group_by}_{stamp}.csv"
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    xlsx_content = _xlsx_bytes(rows=rows, headers=headers)
    filename = f"sales_order_report_{'full' if export_full else group_by}_{stamp}.xlsx"
    return StreamingResponse(
        io.BytesIO(xlsx_content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/reports/sales-orders/filter-options")
async def get_sales_order_report_filter_options(
    _: CurrentUser,
    start_date: date = Query(...),
    end_date: date = Query(...),
    db: AsyncSession = Depends(get_db),
):
    if end_date < start_date:
        return {"item_options": [], "source_options": [], "customer_options": []}
    return await _build_sales_order_filter_options(db, start_date=start_date, end_date=end_date)


@router.post("/bank-convert")
async def bank_convert(
    _: CurrentUser,
    file: UploadFile = File(...),
    format_type: str = Form(...),
    output_type: Literal["csv", "xlsx"] = Form("csv"),
):
    """Convert uploaded bank statement PDF into CSV/XLSX by selected parser format."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    parser = BANK_CONVERT_PARSERS.get(format_type)
    if not parser:
        raise HTTPException(status_code=400, detail="Unsupported format_type")

    pdf_bytes = await file.read()
    try:
        df = parser(pdf_bytes)
    except ValueError:
        raise HTTPException(status_code=400, detail="Format does not match selected bank")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to parse PDF: {exc}") from exc

    file_stem = (file.filename.rsplit(".", 1)[0] or "bank_statement").replace(" ", "_")
    if output_type == "xlsx":
        output = io.BytesIO()
        df.to_excel(output, index=False)
        output.seek(0)
        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{file_stem}_{format_type}.xlsx"'},
        )

    csv_text = df.to_csv(index=False)
    return StreamingResponse(
        iter([csv_text]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{file_stem}_{format_type}.csv"'},
    )
