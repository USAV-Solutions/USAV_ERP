import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.engine.result import ScalarResult

import app.models  # Pre-import to resolve circular dependencies
from app.modules.orders.models import Order, OrderPlatform
from app.modules.orders.routes import (
    verify_order_photos,
    verify_shelf_boxes,
    PhotoStationVerifyRequest,
    ShelfVerifyRequest,
)

@pytest.mark.asyncio
async def test_verify_order_photos_not_found():
    """Verify verify_order_photos handles a non-existent order number correctly."""
    # Mock DB select query returning None
    mock_scalar_result = MagicMock(spec=ScalarResult)
    mock_scalar_result.first = MagicMock(return_value=None)
    mock_execute_result = MagicMock()
    mock_execute_result.scalars = MagicMock(return_value=mock_scalar_result)
    
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_execute_result)
    
    body = PhotoStationVerifyRequest(
        order_number="NON_EXISTENT",
        slip_photo_path="/volume1/photo/123_slip.jpg",
        box_photo_path="/volume1/photo/123_box.jpg",
    )
    
    res = await verify_order_photos(body=body, db=mock_db)
    
    assert res.success is False
    assert res.verify_status == "UNVERIFIED"
    assert "not found" in res.message.lower()


@pytest.mark.asyncio
async def test_verify_order_photos_missing_tracking():
    """Verify verify_order_photos flags order if tracking number is missing."""
    mock_order = MagicMock(spec=Order)
    mock_order.id = 789
    mock_order.tracking_number = None
    mock_order.packing_metadata = {}
    
    # Mock DB select query returning the order
    mock_scalar_result = MagicMock(spec=ScalarResult)
    mock_scalar_result.first = MagicMock(return_value=mock_order)
    mock_execute_result = MagicMock()
    mock_execute_result.scalars = MagicMock(return_value=mock_scalar_result)
    
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_execute_result)
    
    body = PhotoStationVerifyRequest(
        order_number="AMZ-123",
        slip_photo_path="/volume1/photo/123_slip.jpg",
        box_photo_path="/volume1/photo/123_box.jpg",
    )
    
    res = await verify_order_photos(body=body, db=mock_db)
    
    assert res.success is False
    assert res.verify_status == "ERROR_MISSING_TRACKING"
    assert mock_order.verify_status == "ERROR_MISSING_TRACKING"
    assert mock_order.packing_metadata["slip_photo"] == "/volume1/photo/123_slip.jpg"
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_verify_order_photos_success():
    """Verify verify_order_photos sets status to VERIFIED if order has tracking."""
    mock_order = MagicMock(spec=Order)
    mock_order.id = 789
    mock_order.tracking_number = "940015010615125685366"
    mock_order.packing_metadata = {}
    
    # Mock DB select query returning the order
    mock_scalar_result = MagicMock(spec=ScalarResult)
    mock_scalar_result.first = MagicMock(return_value=mock_order)
    mock_execute_result = MagicMock()
    mock_execute_result.scalars = MagicMock(return_value=mock_scalar_result)
    
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_execute_result)
    
    body = PhotoStationVerifyRequest(
        order_number="AMZ-123",
        slip_photo_path="/volume1/photo/123_slip.jpg",
        box_photo_path="/volume1/photo/123_box.jpg",
    )
    
    res = await verify_order_photos(body=body, db=mock_db)
    
    assert res.success is True
    assert res.verify_status == "VERIFIED"
    assert mock_order.verify_status == "VERIFIED"
    assert mock_order.packing_metadata["box_photo"] == "/volume1/photo/123_box.jpg"
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_verify_shelf_boxes_match():
    """Verify shelf count validation transitions orders to READY when counts match."""
    mock_order1 = MagicMock(spec=Order)
    mock_order2 = MagicMock(spec=Order)
    
    # Mock DB select query returning a list of 2 verified orders
    mock_scalar_result = MagicMock(spec=ScalarResult)
    mock_scalar_result.all = MagicMock(return_value=[mock_order1, mock_order2])
    mock_execute_result = MagicMock()
    mock_execute_result.scalars = MagicMock(return_value=mock_scalar_result)
    
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_execute_result)
    
    body = ShelfVerifyRequest(
        photo_path="/volume1/photo/shelf.jpg",
        manual_box_count=2,
    )
    
    res = await verify_shelf_boxes(body=body, db=mock_db)
    
    assert res.success is True
    assert res.mismatch is False
    assert res.box_count == 2
    assert res.verified_orders_count == 2
    assert mock_order1.verify_status == "READY"
    assert mock_order2.verify_status == "READY"
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_verify_shelf_boxes_mismatch():
    """Verify shelf count validation transitions orders to ERROR_COUNT_MISMATCH when counts differ."""
    mock_order1 = MagicMock(spec=Order)
    mock_order2 = MagicMock(spec=Order)
    
    # Mock DB select query returning a list of 2 verified orders
    mock_scalar_result = MagicMock(spec=ScalarResult)
    mock_scalar_result.all = MagicMock(return_value=[mock_order1, mock_order2])
    mock_execute_result = MagicMock()
    mock_execute_result.scalars = MagicMock(return_value=mock_scalar_result)
    
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_execute_result)
    
    body = ShelfVerifyRequest(
        photo_path="/volume1/photo/shelf.jpg",
        manual_box_count=3, # 3 boxes manually counted, but only 2 verified orders
    )
    
    res = await verify_shelf_boxes(body=body, db=mock_db)
    
    assert res.success is False
    assert res.mismatch is True
    assert res.box_count == 3
    assert res.verified_orders_count == 2
    assert mock_order1.verify_status == "ERROR_COUNT_MISMATCH"
    assert mock_order2.verify_status == "ERROR_COUNT_MISMATCH"
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_get_pending_verification_orders():
    """Verify get_pending_verification_orders filters correctly."""
    from app.modules.orders.routes import get_pending_verification_orders
    from datetime import datetime
    
    from decimal import Decimal
    
    mock_order1 = MagicMock(spec=Order)
    mock_order1.id = 111
    mock_order1.external_order_id = "SO-111"
    mock_order1.external_order_number = None
    mock_order1.platform = OrderPlatform.AMAZON
    mock_order1.ordered_at = datetime.now()
    mock_order1.total_amount = Decimal("99.99")
    mock_order1.tracking_number = "940015010615125685366"
    
    # Mock DB select query returning the pending order
    mock_scalar_result = MagicMock(spec=ScalarResult)
    mock_scalar_result.all = MagicMock(return_value=[mock_order1])
    mock_execute_result = MagicMock()
    mock_execute_result.scalars = MagicMock(return_value=mock_scalar_result)
    
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_execute_result)
    
    res = await get_pending_verification_orders(db=mock_db)
    
    assert len(res) == 1
    assert res[0].id == 111
    assert res[0].external_order_id == "SO-111"
    assert res[0].platform == "AMAZON"
    assert res[0].total_amount == Decimal("99.99")


@pytest.mark.asyncio
async def test_extract_ocr_from_slip_no_api_key(monkeypatch):
    """Verify that extract_ocr_from_slip returns a clear error if GEMINI_API_KEY is not set."""
    from app.modules.orders.routes import extract_ocr_from_slip
    from fastapi import UploadFile
    import io
    
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    
    mock_file = UploadFile(
        filename="test.jpg",
        file=io.BytesIO(b"dummy image data")
    )
    
    res = await extract_ocr_from_slip(file=mock_file)
    
    assert res.success is False
    assert "Gemini API key is not configured" in res.message
    assert res.platform == "UNKNOWN"


@pytest.mark.asyncio
async def test_extract_ocr_from_slip_success(monkeypatch):
    """Verify extract_ocr_from_slip successfully invokes and parses Gemini API response."""
    from app.modules.orders.routes import extract_ocr_from_slip
    from fastapi import UploadFile
    import io
    from unittest.mock import patch
    
    monkeypatch.setenv("GEMINI_API_KEY", "test_key")
    
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = '{"platform": "EBAY", "order_id": "26-14651-46671", "tracking_number": "9434608106244166618373"}'
    mock_client.models.generate_content.return_value = mock_response
    
    mock_file = UploadFile(
        filename="test.jpg",
        file=io.BytesIO(b"dummy image data")
    )
    
    with patch("google.genai.Client", return_value=mock_client):
        res = await extract_ocr_from_slip(file=mock_file)
        
    assert res.success is True
    assert res.platform == "EBAY"
    assert res.order_id == "26-14651-46671"
    assert res.tracking_number == "9434608106244166618373"

