from io import BytesIO
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import UploadFile

import app.models  # Pre-import to resolve circular dependencies
from app.modules.orders.models import Order, ShippingStatus
from app.modules.orders.routes import import_orders_from_file
from app.modules.orders.schemas.sync import SalesImportFileSource


@pytest.mark.asyncio
async def test_shipping_status_import_skips_unchanged_status():
    order = MagicMock(spec=Order)
    order.shipping_status = ShippingStatus.SHIPPING

    result = MagicMock()
    result.scalars.return_value.all.return_value = [order]
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()

    response = await import_orders_from_file(
        _staff=MagicMock(),
        source=SalesImportFileSource.SHIPPING_STATUS_CSV,
        file=UploadFile(
            filename="shipping-status.csv",
            file=BytesIO(b"order_number,scraped_status\nSO-1,SHIPPING\n"),
        ),
        service=MagicMock(),
        db=db,
    )

    assert response.new_orders == 0
    db.add.assert_not_called()
    db.commit.assert_awaited_once()
