import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi import HTTPException
from sqlalchemy.engine.result import ScalarResult

import app.models  # Pre-import to resolve circular dependencies
from app.modules.orders.models import Order, OrderPlatform, OrderStatus, ShippingStatus
from app.modules.orders.schemas.orders import OrderStatusUpdate, ShippingStatusUpdate
from app.modules.orders.routes import update_order_status, update_shipping_status, _detect_carrier, _parse_tracking_csv


def test_detect_carrier():
    """Verify smart carrier detection based on tracking number patterns."""
    # UPS starts with 1Z and is 18 chars long
    assert _detect_carrier("1Z9999999999999999") == "UPS"
    assert _detect_carrier("1z9999999999999999") == "UPS"

    # USPS starts with 91-95 and is 22 chars long
    assert _detect_carrier("9400100000000000000000") == "USPS"
    assert _detect_carrier("9200100000000000000000") == "USPS"

    # FedEx is 12 or 15 digits
    assert _detect_carrier("123456789012") == "FedEx"
    assert _detect_carrier("123456789012345") == "FedEx"

    # Default fallback
    assert _detect_carrier("ABC123XYZ") == "USPS"


def test_parse_tracking_csv():
    """Verify daily Google Sheet tracking CSV parsing."""
    csv_text = """Platform,Order Number,Buyer Name,Item Title,USAV SKU,Quantity,Ship by date,Item Number,Tracking,Condition,Note
Amazon,114-0294090-0548272,David Deane,Bose Wave,SKU1,1,6/8/2026,B0CYZ49F5D,9334610990370292055203,USED,Expedited
eBay,09-14720-71786,Jason Wade,Bose Wave 3,SKU2,1,6/3/2026,B0CYZ49F5F,,NEW,
ECWID,4768,Joseph Jennings,Bracket,SKU3,1,,00732,9400150106151254121349,USED,
"""
    rows, seen, skipped = _parse_tracking_csv(csv_text)

    # 3 rows seen, 1 skipped (eBay row has empty tracking)
    assert seen == 3
    assert skipped == 1
    assert len(rows) == 2

    assert rows[0]["platform"] == "Amazon"
    assert rows[0]["order_number"] == "114-0294090-0548272"
    assert rows[0]["tracking"] == "9334610990370292055203"

    assert rows[1]["platform"] == "ECWID"
    assert rows[1]["order_number"] == "4768"
    assert rows[1]["tracking"] == "9400150106151254121349"


@pytest.mark.asyncio
async def test_update_order_status_validation_raises_when_no_tracking():
    """Verify update_order_status raises HTTPException if status updated to SHIPPED but tracking is missing."""
    mock_order = MagicMock(spec=Order)
    mock_order.tracking_number = None

    mock_order_repo = MagicMock()
    mock_order_repo.get_with_items = AsyncMock(return_value=mock_order)

    body = OrderStatusUpdate(status=OrderStatus.SHIPPED)

    with pytest.raises(HTTPException) as exc_info:
        await update_order_status(
            order_id=123,
            body=body,
            order_repo=mock_order_repo,
            db=AsyncMock()
        )

    assert exc_info.value.status_code == 400
    assert "Tracking number is required" in exc_info.value.detail


@pytest.mark.asyncio
async def test_update_order_status_validation_succeeds_with_tracking(monkeypatch):
    """Verify update_order_status succeeds if status updated to SHIPPED and tracking is present."""
    monkeypatch.setattr("app.modules.orders.routes.OrderDetail.model_validate", lambda x: x)
    mock_order = MagicMock(spec=Order)
    mock_order.tracking_number = "1Z12345"

    mock_order_repo = MagicMock()
    mock_order_repo.get_with_items = AsyncMock(return_value=mock_order)
    mock_order_repo.update = AsyncMock(return_value=mock_order)

    mock_db = AsyncMock()
    body = OrderStatusUpdate(status=OrderStatus.SHIPPED)

    res = await update_order_status(
        order_id=123,
        body=body,
        order_repo=mock_order_repo,
        db=mock_db
    )

    assert res is not None
    mock_order_repo.update.assert_called_once()


@pytest.mark.asyncio
async def test_update_shipping_status_raises_when_no_tracking():
    """Verify update_shipping_status raises HTTPException when shipping status is SHIPPING but tracking is missing."""
    mock_order = MagicMock(spec=Order)
    mock_order.tracking_number = None

    mock_order_repo = MagicMock()
    mock_order_repo.get_with_items = AsyncMock(return_value=mock_order)

    body = ShippingStatusUpdate(shipping_status=ShippingStatus.SHIPPING, tracking_number=None)

    with pytest.raises(HTTPException) as exc_info:
        await update_shipping_status(
            order_id=123,
            body=body,
            order_repo=mock_order_repo,
            db=AsyncMock()
        )

    assert exc_info.value.status_code == 400
    assert "Tracking number is required" in exc_info.value.detail


@pytest.mark.asyncio
async def test_update_shipping_status_raises_on_duplicate_tracking():
    """Verify update_shipping_status raises HTTPException when tracking number is already assigned to another order."""
    mock_order = MagicMock(spec=Order)
    mock_order.id = 123
    mock_order.tracking_number = None

    mock_duplicate_order = MagicMock(spec=Order)
    mock_duplicate_order.external_order_id = "AMZ-999"

    mock_order_repo = MagicMock()
    mock_order_repo.get_with_items = AsyncMock(return_value=mock_order)

    # Mock database uniqueness check query returning the duplicate order
    mock_scalar_result = MagicMock(spec=ScalarResult)
    mock_scalar_result.first = MagicMock(return_value=mock_duplicate_order)
    mock_execute_result = MagicMock()
    mock_execute_result.scalars = MagicMock(return_value=mock_scalar_result)
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_execute_result)

    body = ShippingStatusUpdate(
        shipping_status=ShippingStatus.SHIPPING,
        tracking_number="9334610990370292055203"
    )

    with pytest.raises(HTTPException) as exc_info:
        await update_shipping_status(
            order_id=123,
            body=body,
            order_repo=mock_order_repo,
            db=mock_db
        )

    assert exc_info.value.status_code == 400
    assert "already assigned to order" in exc_info.value.detail


def test_ebay_client_convert_order_extracts_tracking():
    """Verify that EbayClient._convert_order extracts tracking number and carrier from fulfillments."""
    from app.integrations.ebay.client import EbayClient

    client = EbayClient(store_name="USAV", app_id="app", cert_id="cert", refresh_token="refresh")
    mock_payload = {
        "orderId": "11-222-333",
        "legacyOrderId": "11-222-333",
        "fulfillmentStartInstructions": [
            {
                "shippingStep": {
                    "shipTo": {
                        "fullName": "John Doe",
                        "contactAddress": {
                            "addressLine1": "123 Main St",
                            "city": "San Jose",
                            "stateOrProvince": "CA",
                            "postalCode": "95125",
                            "countryCode": "US"
                        }
                    }
                }
            }
        ],
        "lineItems": [
            {
                "quantity": 1,
                "lineItemCost": {"value": "49.99"},
                "title": "Bose Speaker"
            }
        ],
        "pricingSummary": {
            "priceSubtotal": {"value": "49.99"},
            "deliveryCost": {"value": "0.00"}
        },
        "creationDate": "2026-06-08T10:00:00.000Z",
        "fulfillments": [
            {
                "shipmentTrackingNumber": "1Z999XX00123456789",
                "shippingCarrierCode": "UPS"
            }
        ]
    }

    order = client._convert_order(mock_payload)
    assert order.tracking_number == "1Z999XX00123456789"
    assert order.carrier == "UPS"


def test_parse_tracking_csv_excluding_fba():
    """Verify daily tracking CSV parsing excluding FBA orders section."""
    from app.modules.orders.routes import _parse_tracking_csv_excluding_fba
    
    csv_text = """Platform,Order Number,Buyer Name,Item Title,USAV SKU,Quantity,Ship by date,Item Number,Tracking,Condition,Note
Amazon,113-0720540-1242637,cheddunbar,Bose Radio,,,6/15/2026,,381981758231,USED,
eBay,21-14736-94321,Randas Computer,Bose Radio,,,6/12/2026,,9400108106245253747367,USED,
Walmart,200014728167003,Tiffany Mays,Bose Radio,,,6/11/2026,,940015010615125685366,USED,
--- FBA Orders ---
Amazon,113-9832410-7680208,Sergio Minervini,Bose Solo,,,6/11/2026,,381981750779,USED,
"""
    rows, seen, skipped, skipped_fba = _parse_tracking_csv_excluding_fba(csv_text)
    
    # Matches first 3 rows. The 4th row (FBA divider) triggers section end and breaks the parsing.
    assert seen == 4
    assert len(rows) == 3
    assert skipped == 0
    
    assert rows[0]["platform"] == "Amazon"
    assert rows[0]["order_number"] == "113-0720540-1242637"
    assert rows[0]["tracking"] == "381981758231"
    
    assert rows[1]["platform"] == "eBay"
    assert rows[1]["order_number"] == "21-14736-94321"
    assert rows[1]["tracking"] == "9400108106245253747367"
    
    assert rows[2]["platform"] == "Walmart"
    assert rows[2]["order_number"] == "200014728167003"
    assert rows[2]["tracking"] == "940015010615125685366"

