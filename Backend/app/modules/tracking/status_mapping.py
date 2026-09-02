"""
Shared mapping from a scraped tracking status string to a ``ShippingStatus``.

Used both by the ``SHIPPING_STATUS_CSV`` file import
(``app/modules/orders/routes.py``) and by the tracking scraper runner so the two
paths stay in lock-step.
"""
from __future__ import annotations

from app.modules.orders.models import ShippingStatus

# Scraped statuses the runner is confident enough about to persist. Anything else
# (NOT_FOUND / UNKNOWN / ERROR / RATE_LIMITED / SKIPPED_TBA) leaves the order
# untouched so it is retried on the next run.
_MAP: dict[str, ShippingStatus] = {
    "DELIVERED": ShippingStatus.DELIVERED,
    "SHIPPED": ShippingStatus.SHIPPING,
    "SHIPPING": ShippingStatus.SHIPPING,
    "RETURNED": ShippingStatus.RETURNED,
    "REFUNDED": ShippingStatus.REFUNDED,
    "CANCELLED": ShippingStatus.CANCELLED,
}


def map_scraped_status(scraped_status: str | None) -> ShippingStatus | None:
    """
    Return the ``ShippingStatus`` a scraped status maps to, or ``None`` when the
    scraped value should not change the order's shipping status.

    ``"PENDING"`` (parcelsapp "label created") maps to ``None`` on purpose: the
    order is already ``PENDING`` and we only want to stamp ``tracking_last_checked_at``.
    """
    return _MAP.get((scraped_status or "").strip().upper())
