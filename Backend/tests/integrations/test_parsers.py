"""
Integration parser tests – eBay & Ecwid JSON → ExternalOrder.

These tests validate that the adapter _convert_order / _parse_ecwid_order
methods correctly map raw platform JSON into our normalised ExternalOrder /
ExternalOrderItem dataclasses.  No network calls are made.
"""
import pytest
from datetime import datetime, timezone

from app.integrations.ebay.client import EbayClient
from app.integrations.ecwid.client import EcwidClient
from app.integrations.base import ExternalOrder, ExternalOrderItem


# ==========================================================================
#  FIXTURES – realistic JSON payloads
# ==========================================================================

EBAY_ORDER_JSON = {
    "orderId": "04-12345-67890",
    "legacyOrderId": "110512345678-0",
    "creationDate": "2026-01-20T14:30:00.000Z",
    "buyer": {"email": "buyer@example.com"},
    "fulfillmentStartInstructions": [
        {
            "shippingStep": {
                "shipTo": {
                    "fullName": "Jane Doe",
                    "contactAddress": {
                        "addressLine1": "123 Elm St",
                        "addressLine2": "Apt 4B",
                        "city": "Austin",
                        "stateOrProvince": "TX",
                        "postalCode": "73301",
                        "countryCode": "US",
                    },
                }
            }
        }
    ],
    "lineItems": [
        {
            "lineItemId": "LI-001",
            "sku": "USAV-BLK-NEW",
            "title": "Stand-Up Paddleboard Black",
            "quantity": 2,
            "lineItemCost": {"value": "149.99", "currency": "USD"},
            "total": {"value": "299.98", "currency": "USD"},
        },
        {
            "lineItemId": "LI-002",
            "sku": "USAV-RED-REF",
            "title": "Kayak Paddle Red Refurb",
            "quantity": 1,
            "lineItemCost": {"value": "39.50", "currency": "USD"},
            "total": {"value": "39.50", "currency": "USD"},
        },
    ],
    "pricingSummary": {
        "priceSubtotal": {"value": "339.48", "currency": "USD"},
        "tax": {"value": "28.00", "currency": "USD"},
        "deliveryCost": {"value": "12.99", "currency": "USD"},
        "total": {"value": "380.47", "currency": "USD"},
    },
}

ECWID_ORDER_JSON = {
    "orderNumber": 98765,
    "vendorOrderNumber": "VO-98765",
    "email": "customer@example.com",
    "createTimestamp": 1769990400,  # 2026-01-02T00:00:00 UTC
    "shippingPerson": {
        "name": "John Smith",
        "street": "456 Oak Ave",
        "city": "Portland",
        "stateOrProvinceCode": "OR",
        "postalCode": "97201",
        "countryCode": "US",
    },
    "items": [
        {
            "id": 501,
            "sku": "ECW-BOARD-01",
            "name": "Inflatable SUP 10'6",
            "quantity": 1,
            "price": 499.00,
        },
        {
            "id": 502,
            "sku": "ECW-FIN-02",
            "name": "Replacement Fin Set",
            "quantity": 3,
            "price": 15.99,
        },
    ],
    "subtotal": 546.97,
    "tax": 49.23,
    "shipping": 0.00,
    "total": 596.20,
    "currency": "USD",
}


# ==========================================================================
#  eBay parser tests
# ==========================================================================

class TestEbayParser:
    """Validate EbayClient._convert_order mapping."""

    @pytest.fixture
    def client(self) -> EbayClient:
        """Instantiate a client with dummy creds (no network needed)."""
        return EbayClient(
            store_name="USAV",
            app_id="FAKE",
            cert_id="FAKE",
            refresh_token="FAKE",
        )

    def test_order_header_fields(self, client: EbayClient):
        order = client._convert_order(EBAY_ORDER_JSON)

        assert isinstance(order, ExternalOrder)
        assert order.platform_order_id == "04-12345-67890"
        assert order.platform_order_number == "110512345678-0"
        assert order.customer_email == "buyer@example.com"

    def test_shipping_address(self, client: EbayClient):
        order = client._convert_order(EBAY_ORDER_JSON)

        assert order.customer_name == "Jane Doe"
        assert order.ship_address_line1 == "123 Elm St"
        assert order.ship_address_line2 == "Apt 4B"
        assert order.ship_city == "Austin"
        assert order.ship_state == "TX"
        assert order.ship_postal_code == "73301"
        assert order.ship_country == "US"

    def test_pricing_summary(self, client: EbayClient):
        order = client._convert_order(EBAY_ORDER_JSON)

        assert order.subtotal == pytest.approx(339.48)
        assert order.tax == pytest.approx(28.00)
        assert order.shipping == pytest.approx(12.99)
        assert order.total == pytest.approx(380.47)
        assert order.currency == "USD"

    def test_line_items_count(self, client: EbayClient):
        order = client._convert_order(EBAY_ORDER_JSON)
        assert len(order.items) == 2

    def test_line_item_details(self, client: EbayClient):
        order = client._convert_order(EBAY_ORDER_JSON)
        item = order.items[0]

        assert isinstance(item, ExternalOrderItem)
        assert item.platform_item_id == "LI-001"
        assert item.platform_sku == "USAV-BLK-NEW"
        assert item.title == "Stand-Up Paddleboard Black"
        assert item.quantity == 2
        assert item.unit_price == pytest.approx(149.99)
        assert item.total_price == pytest.approx(299.98)
        assert item.asin is None  # eBay has no ASIN

    def test_second_line_item(self, client: EbayClient):
        order = client._convert_order(EBAY_ORDER_JSON)
        item = order.items[1]

        assert item.platform_item_id == "LI-002"
        assert item.platform_sku == "USAV-RED-REF"
        assert item.quantity == 1
        assert item.unit_price == pytest.approx(39.50)

    def test_ordered_at_parsed(self, client: EbayClient):
        order = client._convert_order(EBAY_ORDER_JSON)
        assert order.ordered_at is not None
        assert order.ordered_at.year == 2026
        assert order.ordered_at.month == 1
        assert order.ordered_at.day == 20

    def test_raw_data_preserved(self, client: EbayClient):
        order = client._convert_order(EBAY_ORDER_JSON)
        assert order.raw_data is EBAY_ORDER_JSON
        assert order.items[0].raw_data is EBAY_ORDER_JSON["lineItems"][0]

    def test_missing_shipping_graceful(self, client: EbayClient):
        """Parser should not crash when shipping info is absent."""
        minimal = {
            "orderId": "MIN-001",
            "legacyOrderId": None,
            "creationDate": None,
            "buyer": {},
            "fulfillmentStartInstructions": [],
            "lineItems": [],
            "pricingSummary": {},
        }
        order = client._convert_order(minimal)
        assert order.platform_order_id == "MIN-001"
        assert order.customer_name is None
        assert order.ship_address_line1 is None
        assert order.items == []

    def test_missing_pricing_defaults_zero(self, client: EbayClient):
        """Financial fields should default to 0 when absent."""
        minimal = {
            "orderId": "MIN-002",
            "fulfillmentStartInstructions": [],
            "lineItems": [],
            "pricingSummary": {},
        }
        order = client._convert_order(minimal)
        assert order.subtotal == 0.0
        assert order.tax == 0.0
        assert order.shipping == 0.0
        assert order.total == 0.0


# ==========================================================================
#  Ecwid parser tests
# ==========================================================================

class TestEcwidParser:
    """Validate EcwidClient._parse_ecwid_order mapping."""

    @pytest.fixture
    def client(self) -> EcwidClient:
        return EcwidClient(
            store_id="12345",
            access_token="FAKE_TOKEN",
        )

    def test_order_header_fields(self, client: EcwidClient):
        order = client._parse_ecwid_order(ECWID_ORDER_JSON)

        assert isinstance(order, ExternalOrder)
        assert order.platform_order_id == "98765"  # orderNumber stringified
        assert order.platform_order_number == "VO-98765"
        assert order.customer_email == "customer@example.com"

    def test_shipping_address(self, client: EcwidClient):
        order = client._parse_ecwid_order(ECWID_ORDER_JSON)

        assert order.customer_name == "John Smith"
        assert order.ship_address_line1 == "456 Oak Ave"
        assert order.ship_address_line2 is None  # Ecwid doesn't split
        assert order.ship_city == "Portland"
        assert order.ship_state == "OR"
        assert order.ship_postal_code == "97201"
        assert order.ship_country == "US"

    def test_pricing(self, client: EcwidClient):
        order = client._parse_ecwid_order(ECWID_ORDER_JSON)

        assert order.subtotal == pytest.approx(546.97)
        assert order.tax == pytest.approx(49.23)
        assert order.shipping == pytest.approx(0.0)
        assert order.total == pytest.approx(596.20)
        assert order.currency == "USD"

    def test_line_items_count(self, client: EcwidClient):
        order = client._parse_ecwid_order(ECWID_ORDER_JSON)
        assert len(order.items) == 2

    def test_line_item_details(self, client: EcwidClient):
        order = client._parse_ecwid_order(ECWID_ORDER_JSON)
        item = order.items[0]

        assert item.platform_item_id == "501"  # id stringified
        assert item.platform_sku == "ECW-BOARD-01"
        assert item.title == "Inflatable SUP 10'6"
        assert item.quantity == 1
        assert item.unit_price == pytest.approx(499.00)
        assert item.total_price == pytest.approx(499.00)
        assert item.asin is None

    def test_multi_quantity_item(self, client: EcwidClient):
        order = client._parse_ecwid_order(ECWID_ORDER_JSON)
        item = order.items[1]

        assert item.platform_item_id == "502"
        assert item.quantity == 3
        assert item.unit_price == pytest.approx(15.99)
        assert item.total_price == pytest.approx(15.99 * 3)

    def test_ordered_at_from_unix_timestamp(self, client: EcwidClient):
        order = client._parse_ecwid_order(ECWID_ORDER_JSON)
        assert order.ordered_at is not None
        assert isinstance(order.ordered_at, datetime)

    def test_raw_data_preserved(self, client: EcwidClient):
        order = client._parse_ecwid_order(ECWID_ORDER_JSON)
        assert order.raw_data is ECWID_ORDER_JSON
        assert order.items[0].raw_data is ECWID_ORDER_JSON["items"][0]

    def test_missing_vendor_order_number_fallback(self, client: EcwidClient):
        """If vendorOrderNumber is None, falls back to orderNumber."""
        data = {
            "orderNumber": 111,
            "vendorOrderNumber": None,
            "shippingPerson": {},
            "items": [],
            "subtotal": 0,
            "tax": 0,
            "shipping": 0,
            "total": 0,
        }
        order = client._parse_ecwid_order(data)
        assert order.platform_order_id == "111"
        assert order.platform_order_number == "111"  # fallback

    def test_empty_items(self, client: EcwidClient):
        data = {
            "orderNumber": 222,
            "shippingPerson": {},
            "items": [],
            "subtotal": 0,
            "tax": 0,
            "shipping": 0,
            "total": 0,
        }
        order = client._parse_ecwid_order(data)
        assert order.items == []

    def test_missing_shipping_person(self, client: EcwidClient):
        """Graceful handling when shippingPerson is absent."""
        data = {
            "orderNumber": 333,
            "items": [],
            "subtotal": 0,
            "tax": 0,
            "shipping": 0,
            "total": 0,
        }
        order = client._parse_ecwid_order(data)
        assert order.customer_name is None
        assert order.ship_city is None
