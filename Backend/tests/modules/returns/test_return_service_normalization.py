from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

from app.models import OrderPlatform, ReturnNormalizedStatus
from app.modules.returns.service import ReturnSyncService


def _build_service() -> ReturnSyncService:
    return ReturnSyncService(
        session=MagicMock(),
        sync_repo=MagicMock(),
        record_repo=MagicMock(),
        order_repo=MagicMock(),
    )


def test_normalize_ebay_cancellation_only():
    service = _build_service()
    raw_order = (
        {
            "orderId": "EB-1",
            "cancelStatus": {"cancelState": "CANCELED", "cancelledDate": "2026-06-08T10:00:00Z"},
            "lineItems": [
                {"legacyItemId": "I1", "sku": "SKU-1", "title": "Item 1", "quantity": 2, "cancelledQuantity": 2},
            ],
            "pricingSummary": {"total": {"value": "25.00", "currency": "USD"}},
        }
    )

    record = service._normalize_ebay_order_record(OrderPlatform.EBAY_USAV, "EBAY_USAV_API", raw_order)

    assert record is not None
    assert record.normalized_status == ReturnNormalizedStatus.CANCELLED
    assert record.external_record_key == "order:EB-1"
    assert record.items[0].cancelled_qty == 2


def test_normalize_ebay_return_case_partial_quantity():
    service = _build_service()
    record = service._normalize_ebay_return_case(
        OrderPlatform.EBAY_USAV,
        "EBAY_USAV_API",
        {
            "returnId": "RET-1",
            "legacyOrderId": "ORD-1",
            "status": "PARTIAL",
            "items": [
                {"legacyItemId": "I1", "sku": "SKU-1", "title": "Item 1", "quantity": 3, "returnedQuantity": 1},
            ],
            "lastModifiedDate": "2026-06-08T12:00:00Z",
        },
    )

    assert record is not None
    assert record.normalized_status == ReturnNormalizedStatus.PARTIALLY_RETURNED
    assert record.items[0].returned_qty == 1


def test_normalize_ebay_refund_without_return_case():
    service = _build_service()
    raw_order = (
        {
            "orderId": "EB-2",
            "paymentSummary": {
                "paymentStatus": "PARTIALLY_REFUNDED",
                "refunds": [{"amount": {"value": "4.50"}}],
            },
            "lineItems": [{"legacyItemId": "I1", "sku": "SKU-1", "title": "Item 1", "quantity": 1}],
        }
    )

    record = service._normalize_ebay_order_record(OrderPlatform.EBAY_USAV, "EBAY_USAV_API", raw_order)

    assert record is not None
    assert record.normalized_status == ReturnNormalizedStatus.PARTIALLY_REFUNDED
    assert record.refunded_amount == Decimal("4.50")


def test_ebay_order_candidate_filter_uses_list_payload_fields():
    service = _build_service()

    assert service._is_ebay_order_candidate(
        {
            "cancelStatus": {"cancelState": "CANCELED"},
            "paymentSummary": {"refunds": []},
        }
    )
    assert service._is_ebay_order_candidate(
        {
            "cancelStatus": {"cancelState": "NONE_REQUESTED"},
            "paymentSummary": {"refunds": [{"amount": {"value": "1.00"}}]},
        }
    )
    assert not service._is_ebay_order_candidate(
        {
            "cancelStatus": {"cancelState": "NONE_REQUESTED"},
            "paymentSummary": {"refunds": []},
            "orderPaymentStatus": "PAID",
        }
    )


def test_ebay_order_detail_only_needed_for_suspicious_payloads():
    service = _build_service()

    assert service._ebay_order_needs_detail(
        {
            "cancelStatus": {"cancelState": "NONE_REQUESTED"},
            "paymentSummary": {"refunds": [{"amount": {"value": "2.00"}}]},
            "pricingSummary": {"total": {"value": "10.00"}},
            "lineItems": [{"quantity": 1}],
        }
    )
    assert not service._ebay_order_needs_detail(
        {
            "cancelStatus": {"cancelState": "CANCELED"},
            "paymentSummary": {"refunds": [{"amount": {"value": "10.00"}}]},
            "pricingSummary": {"total": {"value": "10.00"}},
            "lineItems": [{"quantity": 1, "cancelledQuantity": 1}],
            "orderPaymentStatus": "FULLY_REFUNDED",
        }
    )


def test_merge_ecwid_returned_over_refunded():
    service = _build_service()
    refunded = service._normalize_ecwid_order_record(
        OrderPlatform.ECWID,
        "ECWID_API",
        {
            "id": 10,
            "paymentStatus": "REFUNDED",
            "fulfillmentStatus": "AWAITING_PROCESSING",
            "currency": "USD",
            "total": 12,
            "refundedAmount": 12,
            "items": [{"productId": "1", "sku": "SKU-1", "name": "Item 1", "quantity": 1}],
        },
    )
    returned = service._normalize_ecwid_order_record(
        OrderPlatform.ECWID,
        "ECWID_API",
        {
            "id": 10,
            "paymentStatus": "REFUNDED",
            "fulfillmentStatus": "RETURNED",
            "currency": "USD",
            "total": 12,
            "refundedAmount": 12,
            "items": [{"productId": "1", "sku": "SKU-1", "name": "Item 1", "quantity": 1}],
        },
    )

    merged = service._merge_record(refunded, returned)

    assert merged.normalized_status == ReturnNormalizedStatus.RETURNED
    assert merged.refunded_amount == Decimal("12")


def test_normalize_ecwid_single_line_refund_sets_return_quantity():
    service = _build_service()
    record = service._normalize_ecwid_order_record(
        OrderPlatform.ECWID,
        "ECWID_API",
        {
            "id": 4718,
            "paymentStatus": "PARTIALLY_REFUNDED",
            "fulfillmentStatus": "SHIPPED",
            "currency": "USD",
            "total": 120,
            "refundedAmount": 20,
            "items": [{"productId": "1", "sku": "01658", "name": "Bose 301 Series IV", "quantity": 1}],
        },
    )

    assert record is not None
    assert record.normalized_status == ReturnNormalizedStatus.PARTIALLY_REFUNDED
    assert record.refunded_amount == Decimal("20")
    assert record.items[0].returned_qty == 1
    assert record.items[0].cancelled_qty == 0
    assert record.items[0].refunded_amount == Decimal("20")


def test_normalize_walmart_partial_cancellation():
    service = _build_service()
    record = service._normalize_walmart_order_record(
        OrderPlatform.WALMART,
        "WALMART_API",
        {
            "purchaseOrderId": "WM-1",
            "orderLines": {
                "orderLine": [
                    {
                        "lineNumber": "1",
                        "item": {"sku": "SKU-1", "productName": "Item 1"},
                        "orderLineQuantity": {"amount": 2},
                        "orderLineStatuses": {"orderLineStatus": [{"status": "Cancelled", "statusQuantity": {"amount": 1}}]},
                    },
                ]
            },
            "orderDate": "2026-06-08T10:00:00Z",
        },
    )

    assert record is not None
    assert record.normalized_status == ReturnNormalizedStatus.PARTIALLY_CANCELLED
    assert record.items[0].cancelled_qty == 1


def test_normalize_walmart_return_with_refund_detail():
    service = _build_service()
    record = service._normalize_walmart_return_record(
        OrderPlatform.WALMART,
        "WALMART_API",
        {
            "returnOrderId": "WR-1",
            "purchaseOrderId": "WM-1",
            "status": "COMPLETED",
            "returnOrderLines": [
                {
                    "lineNumber": "1",
                    "item": {"sku": "SKU-1", "productName": "Item 1"},
                    "orderedQuantity": 2,
                    "returnOrderLineQuantity": {"amount": 2},
                    "refundAmount": {"amount": "9.99"},
                }
            ],
            "returnDate": "2026-06-08T11:00:00Z",
            "currency": "USD",
        },
    )

    assert record is not None
    assert record.normalized_status == ReturnNormalizedStatus.RETURNED
    assert record.refunded_amount == Decimal("9.99")
