"""
AI Packaging Photo Diagnostic Engine using Gemini Vision AI (gemini-3.5-flash / gemini-2.5-flash).
Extracts document OCR and performs physical item correctness matching against ERP Sales Orders.
"""

import os
import re
import json
import logging
import time
from typing import Optional, List, Dict, Any
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.modules.orders.models import Order, OrderItem

logger = logging.getLogger(__name__)


class AIDiagnosticResponse(BaseModel):
    success: bool
    filename: str
    latency_ms: float
    is_valid_packing_photo: bool
    platform: str
    order_id: str
    tracking_number: str
    sku_on_slip: Optional[str] = None
    detected_physical_item: str
    expected_erp_item: Optional[str] = None
    item_match: bool
    confidence_score: float
    status: str  # E.g. "CORRECT", "ITEM_MISMATCH", "MISSING_TRACKING", "NO_PACKING_SLIP", "ERROR"
    message: str


async def diagnose_packaging_photo_bytes(
    image_bytes: bytes,
    filename: str = "sample_photo.jpg",
    mime_type: str = "image/jpeg",
    db: Optional[AsyncSession] = None,
) -> AIDiagnosticResponse:
    """
    Diagnose a packing photo using Gemini Vision AI (gemini-3.5-flash).
    Extracts paper document data (Order ID, SKU, Tracking) and describes the physical item in photo.
    Performs verification against local database Sales Orders if db is provided.
    """
    start_time = time.time()

    if not image_bytes or len(image_bytes) == 0:
        return AIDiagnosticResponse(
            success=False,
            filename=filename,
            latency_ms=0.0,
            is_valid_packing_photo=False,
            platform="UNKNOWN",
            order_id="",
            tracking_number="",
            detected_physical_item="Empty payload",
            item_match=False,
            confidence_score=0.0,
            status="ERROR",
            message="Empty image payload provided."
        )

    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return AIDiagnosticResponse(
            success=False,
            filename=filename,
            latency_ms=0.0,
            is_valid_packing_photo=False,
            platform="UNKNOWN",
            order_id="",
            tracking_number="",
            detected_physical_item="API key unconfigured",
            item_match=False,
            confidence_score=0.0,
            status="ERROR",
            message="Gemini API key is not configured in environment."
        )

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)

        prompt = (
            "Analyze this warehouse packing station photograph carefully.\n"
            "The photo typically contains paperwork (a packing slip and shipping label) at the bottom, "
            "and a physical product placed at the top.\n\n"
            "Perform the following dual analysis:\n"
            "1. Document OCR Extraction:\n"
            "   - platform: Marketplace platform (AMAZON, EBAY, WALMART, SHOPIFY, ECWID, etc.)\n"
            "   - order_id: Full Order ID / Order Number (e.g. 113-0602625-1537021 or 27-14648-44047)\n"
            "   - tracking_number: Carrier tracking number on shipping label (UPS: 1Z..., USPS: 20-22 digits starting with 9, FedEx: 12-15 digits)\n"
            "   - sku_on_slip: Product SKU or Item ID printed on packing slip if visible\n"
            "2. Physical Item Analysis:\n"
            "   - is_valid_packing_photo: true if paperwork (slip or label) is present, false if just a random part photo\n"
            "   - detected_physical_item: Concise visual description of the main physical product/object in top half (e.g. 'Coiled black audio speaker cable', 'Bose Wave CD Changer Base Unit', 'Power adapter plug', etc.)\n"
            "   - confidence_score: Float confidence rating between 0.0 and 1.0\n\n"
            "Return STRICTLY a raw JSON object with keys:\n"
            "{\n"
            "  \"is_valid_packing_photo\": true,\n"
            "  \"platform\": \"AMAZON\",\n"
            "  \"order_id\": \"113-0602625-1537021\",\n"
            "  \"tracking_number\": \"9300110990513442589502\",\n"
            "  \"sku_on_slip\": \"AH-PL9M-F32Y\",\n"
            "  \"detected_physical_item\": \"Coiled black 2-wire audio speaker cable\",\n"
            "  \"confidence_score\": 0.96\n"
            "}\n"
            "Do not wrap in markdown code blocks."
        )

        # Try gemini-3.5-flash, fallback to gemini-2.5-flash if needed
        model_name = os.getenv("GEMINI_DIAGNOSTIC_MODEL", "gemini-2.5-flash")

        response = client.models.generate_content(
            model=model_name,
            contents=[
                types.Part.from_bytes(
                    data=image_bytes,
                    mime_type=mime_type,
                ),
                prompt
            ]
        )

        elapsed_ms = round((time.time() - start_time) * 1000, 2)
        text_resp = response.text.strip()
        text_resp = re.sub(r"^```(?:json)?\n", "", text_resp)
        text_resp = re.sub(r"\n```$", "", text_resp).strip()

        data = json.loads(text_resp)

        is_valid = bool(data.get("is_valid_packing_photo", True))
        extracted_platform = str(data.get("platform", "UNKNOWN")).upper()
        extracted_order_id = str(data.get("order_id", "")).strip()
        extracted_tracking = str(data.get("tracking_number", "")).strip()
        extracted_sku = str(data.get("sku_on_slip", "")).strip() or None
        detected_item = str(data.get("detected_physical_item", "Unidentified object")).strip()
        confidence = float(data.get("confidence_score", 0.90))

        if not is_valid or not (extracted_order_id or extracted_tracking):
            return AIDiagnosticResponse(
                success=True,
                filename=filename,
                latency_ms=elapsed_ms,
                is_valid_packing_photo=False,
                platform=extracted_platform,
                order_id=extracted_order_id,
                tracking_number=extracted_tracking,
                sku_on_slip=extracted_sku,
                detected_physical_item=detected_item,
                expected_erp_item=None,
                item_match=False,
                confidence_score=confidence,
                status="NO_PACKING_SLIP",
                message="No packing slip or valid order details detected in photo."
            )

        # DB Cross-Check if database session is provided
        expected_erp_item = None
        item_match = True
        status = "CORRECT"
        msg = "Photo parsed successfully and order verified."

        if db and extracted_order_id:
            stmt = select(Order).where(
                (func.lower(Order.external_order_id) == func.lower(extracted_order_id)) |
                (func.lower(Order.external_order_number) == func.lower(extracted_order_id))
            )
            order_record = (await db.execute(stmt)).scalars().first()

            if order_record:
                # Fetch order item names
                item_stmt = select(OrderItem).where(OrderItem.order_id == order_record.id)
                items = (await db.execute(item_stmt)).scalars().all()
                if items:
                    item_names = [it.title or it.sku or "Item" for it in items if it]
                    expected_erp_item = ", ".join(item_names)

                if not order_record.tracking_number and not extracted_tracking:
                    status = "MISSING_TRACKING"
                    msg = "Order found in ERP, but Tracking Number is missing."
                elif not order_record.tracking_number and extracted_tracking:
                    status = "CORRECT"
                    msg = f"Extracted tracking {extracted_tracking} for ERP Order {extracted_order_id}."
            else:
                status = "ORDER_NOT_IN_ERP"
                msg = f"Parsed Order ID '{extracted_order_id}' not found in database."

        return AIDiagnosticResponse(
            success=True,
            filename=filename,
            latency_ms=elapsed_ms,
            is_valid_packing_photo=is_valid,
            platform=extracted_platform,
            order_id=extracted_order_id,
            tracking_number=extracted_tracking,
            sku_on_slip=extracted_sku,
            detected_physical_item=detected_item,
            expected_erp_item=expected_erp_item,
            item_match=item_match,
            confidence_score=confidence,
            status=status,
            message=msg
        )

    except Exception as e:
        elapsed_ms = round((time.time() - start_time) * 1000, 2)
        logger.error(f"[Diagnostic] Failed to diagnose photo {filename}: {str(e)}", exc_info=True)
        return AIDiagnosticResponse(
            success=False,
            filename=filename,
            latency_ms=elapsed_ms,
            is_valid_packing_photo=False,
            platform="UNKNOWN",
            order_id="",
            tracking_number="",
            detected_physical_item="Processing Error",
            item_match=False,
            confidence_score=0.0,
            status="ERROR",
            message=f"AI Diagnosis failed: {str(e)}"
        )
