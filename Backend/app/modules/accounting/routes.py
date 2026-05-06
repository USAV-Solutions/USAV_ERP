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
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, require_roles
from app.core.database import get_db
from app.models import UserRole
from app.models.entities import ProductVariant
from app.models.purchasing import PurchaseOrder, PurchaseOrderItem, Vendor
from app.modules.accounting.bank_convert_utils import BANK_CONVERT_PARSERS


router = APIRouter(
    prefix="/accounting",
    tags=["Accounting"],
    dependencies=[Depends(require_roles(UserRole.ADMIN, UserRole.ACCOUNTANT))],
)

GroupByType = Literal["sku", "week", "month", "quarter", "year", "source", "vendor"]


def _group_value(group_by: GroupByType, order_date: date | None, sku: str | None, source: str | None, vendor: str | None) -> str:
    if group_by == "sku":
        return (sku or "UNMATCHED").strip() or "UNMATCHED"
    if group_by == "source":
        return (source or "UNKNOWN").strip() or "UNKNOWN"
    if group_by == "vendor":
        return (vendor or "UNKNOWN").strip() or "UNKNOWN"
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
) -> list[dict[str, object]]:
    stmt = (
        select(
            PurchaseOrder.order_date.label("order_date"),
            PurchaseOrder.po_number.label("order_number"),
            PurchaseOrderItem.external_item_name.label("item"),
            ProductVariant.full_sku.label("sku"),
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
    rows = (await db.execute(stmt)).mappings().all()

    grouped: dict[str, dict[str, object]] = {}
    for row in rows:
        key = _group_value(
            group_by=group_by,
            order_date=row["order_date"],
            sku=row["sku"],
            source=row["source"],
            vendor=row["vendor"],
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

    report_rows: list[dict[str, object]] = []
    for _, value in sorted(grouped.items(), key=lambda item: item[0]):
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


@router.get("/reports")
async def get_reports_stub(_: CurrentUser):
    """Phase 1 scaffold endpoint for accounting reports."""
    return {"message": "Report module connected"}


@router.get("/reports/purchase-orders")
async def get_purchase_order_reports(
    _: CurrentUser,
    start_date: date = Query(...),
    end_date: date = Query(...),
    group_by: GroupByType = Query("month"),
    db: AsyncSession = Depends(get_db),
):
    if end_date < start_date:
        return {"rows": [], "message": "end_date must be on or after start_date"}
    rows = await _build_purchase_order_report(db, start_date=start_date, end_date=end_date, group_by=group_by)
    return {"rows": rows}


@router.get("/reports/purchase-orders/export")
async def export_purchase_order_reports(
    _: CurrentUser,
    start_date: date = Query(...),
    end_date: date = Query(...),
    group_by: GroupByType = Query("month"),
    file_type: Literal["csv", "xlsx"] = Query("csv"),
    db: AsyncSession = Depends(get_db),
):
    if end_date < start_date:
        end_date = start_date
    rows = await _build_purchase_order_report(db, start_date=start_date, end_date=end_date, group_by=group_by)
    headers = ["group", "order_date", "order_number", "item", "sku", "source", "quantity", "total_price", "tax", "shipping", "handling", "vendor"]
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    if file_type == "csv":
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
        filename = f"purchase_order_report_{group_by}_{stamp}.csv"
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    xlsx_content = _xlsx_bytes(rows=rows, headers=headers)
    filename = f"purchase_order_report_{group_by}_{stamp}.xlsx"
    return StreamingResponse(
        io.BytesIO(xlsx_content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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

    if format_type == "format_7":
        raise HTTPException(status_code=501, detail="Format 7 parser is not implemented yet")

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

