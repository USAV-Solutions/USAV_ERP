"""
Returns module API routes.
"""
import logging
from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser
from app.core.config import settings
from app.core.database import get_db
from app.integrations.base import BasePlatformClient
from app.integrations.ebay.client import EbayClient
from app.integrations.ecwid.client import EcwidClient
from app.integrations.walmart.client import WalmartClient
from app.modules.orders.models import OrderPlatform
from app.modules.returns.dependencies import (
    get_return_record_repo,
    get_return_service,
    get_return_sync_repo,
    get_zoho_return_service,
)
from app.modules.returns.models import ReturnNormalizedStatus
from app.modules.returns.schemas import (
    ReturnListResponse,
    ReturnRecordBrief,
    ReturnRecordDetail,
    ReturnZohoLineValidationResponse,
    ReturnZohoSyncRangeRequest,
    ReturnZohoSyncRangeResponse,
    ReturnZohoSyncStatusResponse,
    ReturnZohoValidationResponse,
    ReturnSyncRangeRequest,
    ReturnSyncRequest,
    ReturnSyncResponse,
    ReturnSyncStateResponse,
    ReturnSyncStatusResponse,
)
from app.modules.returns.service import ReturnSyncService
from app.modules.returns.zoho_sync import ZohoReturnValidation, ZohoReturnSyncService
from app.repositories.returns.record_repository import ReturnRecordRepository
from app.repositories.returns.sync_repository import ReturnSyncStateRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/returns", tags=["Returns"])

_PLATFORM_TO_SOURCE: dict[str, str] = {
    "EBAY_MEKONG": "EBAY_MEKONG_API",
    "EBAY_USAV": "EBAY_USAV_API",
    "EBAY_DRAGON": "EBAY_DRAGON_API",
    "ECWID": "ECWID_API",
    "WALMART": "WALMART_API",
}


def _build_platform_clients() -> dict[str, BasePlatformClient]:
    clients: dict[str, BasePlatformClient] = {}

    ebay_stores = {
        "EBAY_MEKONG": settings.ebay_refresh_token_mekong,
        "EBAY_USAV": settings.ebay_refresh_token_usav,
        "EBAY_DRAGON": settings.ebay_refresh_token_dragon,
    }
    if settings.ebay_app_id and settings.ebay_cert_id:
        for store_key, refresh_token in ebay_stores.items():
            if not refresh_token:
                continue
            clients[store_key] = EbayClient(
                store_name=store_key.replace("EBAY_", ""),
                app_id=settings.ebay_app_id,
                cert_id=settings.ebay_cert_id,
                refresh_token=refresh_token,
                sandbox=settings.ebay_sandbox,
            )

    if settings.ecwid_store_id:
        clients["ECWID"] = EcwidClient(
            store_id=settings.ecwid_store_id,
            access_token=settings.ecwid_secret,
            api_base_url=settings.ecwid_api_base_url,
        )

    if settings.walmart_client_id and settings.walmart_client_secret:
        clients["WALMART"] = WalmartClient(
            client_id=settings.walmart_client_id,
            client_secret=settings.walmart_client_secret,
            api_base_url=settings.walmart_api_base_url,
        )

    return clients


def _zoho_validation_response(result: ZohoReturnValidation) -> ReturnZohoValidationResponse:
    return ReturnZohoValidationResponse(
        record_id=result.record_id,
        status=result.status,
        blockers=result.blockers,
        zoho_salesorder_id=result.zoho_salesorder_id,
        zoho_salesreturn_id=result.zoho_salesreturn_id,
        zoho_salesreturn_number=result.zoho_salesreturn_number,
        line_items=[
            ReturnZohoLineValidationResponse(
                return_item_id=item.return_item_id,
                linked_order_item_id=item.linked_order_item_id,
                quantity=item.quantity,
                zoho_salesorder_item_id=item.zoho_salesorder_item_id,
                status=item.status,
                message=item.message,
            )
            for item in result.line_items
        ],
    )


@router.get("", response_model=ReturnListResponse)
async def list_returns(
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    platform: Annotated[Optional[OrderPlatform], Query()] = None,
    normalized_status: Annotated[Optional[str], Query()] = None,
    source: Annotated[Optional[str], Query()] = None,
    ordered_at_from: Annotated[Optional[datetime], Query()] = None,
    ordered_at_to: Annotated[Optional[datetime], Query()] = None,
    event_at_from: Annotated[Optional[datetime], Query()] = None,
    event_at_to: Annotated[Optional[datetime], Query()] = None,
    sort_by: Annotated[str, Query(pattern="^(event_at|ordered_at|refunded_amount|external_order_id)$")] = "event_at",
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "desc",
    search: Annotated[Optional[str], Query()] = None,
    record_repo: ReturnRecordRepository = Depends(get_return_record_repo),
):
    status_filter = None
    if normalized_status:
        try:
            status_filter = ReturnNormalizedStatus(normalized_status)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid return status: {normalized_status}",
            ) from exc

    rows, total, summary_counts = await record_repo.list_records(
        skip=skip,
        limit=limit,
        platform=platform,
        normalized_status=status_filter,
        source=source,
        ordered_at_from=ordered_at_from,
        ordered_at_to=ordered_at_to,
        event_at_from=event_at_from,
        event_at_to=event_at_to,
        sort_by=sort_by,
        sort_dir=sort_dir,
        search=search,
    )
    items = []
    for row in rows:
        returned_qty_total = sum(int(item.returned_qty or 0) for item in row.items)
        cancelled_qty_total = sum(int(item.cancelled_qty or 0) for item in row.items)
        items.append(
            ReturnRecordBrief(
                id=row.id,
                platform=row.platform,
                source=row.source,
                external_record_key=row.external_record_key,
                external_order_id=row.external_order_id,
                external_return_id=row.external_return_id,
                linked_order_id=row.linked_order_id,
                customer_name=row.customer_name,
                customer_email=row.customer_email,
                ordered_at=row.ordered_at,
                event_at=row.event_at,
                last_source_updated_at=row.last_source_updated_at,
                normalized_status=row.normalized_status,
                source_status=row.source_status,
                source_substatus=row.source_substatus,
                reason=row.reason,
                order_total_amount=row.order_total_amount,
                refunded_amount=row.refunded_amount,
                currency=row.currency,
                zoho_salesreturn_id=getattr(row, "zoho_salesreturn_id", None),
                zoho_salesreturn_number=getattr(row, "zoho_salesreturn_number", None),
                zoho_sync_status=getattr(row, "zoho_sync_status", None) or "PENDING",
                zoho_sync_error=getattr(row, "zoho_sync_error", None),
                zoho_synced_at=getattr(row, "zoho_synced_at", None),
                item_count=len(row.items or []),
                returned_qty_total=returned_qty_total,
                cancelled_qty_total=cancelled_qty_total,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
        )
    return ReturnListResponse(total=total, skip=skip, limit=limit, items=items, summary_counts=summary_counts)


@router.post("/{record_id}/zoho/validate", response_model=ReturnZohoValidationResponse)
async def validate_return_for_zoho(
    record_id: int,
    _admin: AdminUser,
    service: ZohoReturnSyncService = Depends(get_zoho_return_service),
):
    try:
        result = await service.validate_return_for_zoho(record_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _zoho_validation_response(result)


@router.post("/{record_id}/zoho/sync", response_model=ReturnZohoValidationResponse)
async def sync_return_to_zoho(
    record_id: int,
    _admin: AdminUser,
    service: ZohoReturnSyncService = Depends(get_zoho_return_service),
):
    try:
        result = await service.sync_return_to_zoho(record_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _zoho_validation_response(result)


@router.post("/zoho/sync/range", response_model=ReturnZohoSyncRangeResponse)
async def sync_returns_to_zoho_range(
    body: ReturnZohoSyncRangeRequest,
    _admin: AdminUser,
    service: ZohoReturnSyncService = Depends(get_zoho_return_service),
):
    results = await service.sync_eligible_returns_to_zoho(
        platform=body.platform,
        since=body.since,
        until=body.until,
        limit=body.limit,
    )
    responses = [_zoho_validation_response(result) for result in results]
    return ReturnZohoSyncRangeResponse(
        total=len(responses),
        synced=sum(1 for item in responses if item.status.value == "SYNCED"),
        blocked=sum(
            1
            for item in responses
            if item.status.value
            in {"MISSING_LOCAL_ORDER", "MISSING_ZOHO_ORDER", "MISSING_LINE_ITEM_MAPPING", "QUANTITY_CONFLICT"}
        ),
        failed=sum(1 for item in responses if item.status.value == "ERROR"),
        items=responses,
    )


@router.get("/zoho/sync/status", response_model=ReturnZohoSyncStatusResponse)
async def zoho_sync_status(
    service: ZohoReturnSyncService = Depends(get_zoho_return_service),
):
    return ReturnZohoSyncStatusResponse(
        total_records=await service.count_returns(),
        counts_by_status=await service.count_by_zoho_status(),
    )


@router.get("/{record_id}", response_model=ReturnRecordDetail)
async def get_return_record(
    record_id: int,
    record_repo: ReturnRecordRepository = Depends(get_return_record_repo),
):
    record = await record_repo.get_with_items(record_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Return record {record_id} not found.")
    detail = ReturnRecordDetail.model_validate(record)
    detail.item_count = len(record.items or [])
    detail.returned_qty_total = sum(int(item.returned_qty or 0) for item in record.items)
    detail.cancelled_qty_total = sum(int(item.cancelled_qty or 0) for item in record.items)
    return detail


@router.post("/sync", response_model=list[ReturnSyncResponse])
async def sync_returns(
    body: ReturnSyncRequest,
    _admin: AdminUser,
    service: ReturnSyncService = Depends(get_return_service),
):
    clients = _build_platform_clients()
    if body.platform:
        if body.platform not in clients:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Platform '{body.platform}' is not configured or unknown.",
            )
        result = await service.sync_platform(
            body.platform,
            clients[body.platform],
            source=_PLATFORM_TO_SOURCE.get(body.platform, f"{body.platform}_API"),
        )
        return [result]

    results = []
    for name, client in clients.items():
        result = await service.sync_platform(
            name,
            client,
            source=_PLATFORM_TO_SOURCE.get(name, f"{name}_API"),
        )
        results.append(result)
    return results


@router.post("/sync/range", response_model=list[ReturnSyncResponse])
async def sync_returns_range(
    body: ReturnSyncRangeRequest,
    _admin: AdminUser,
    service: ReturnSyncService = Depends(get_return_service),
):
    clients = _build_platform_clients()
    if body.platform:
        if body.platform not in clients:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Platform '{body.platform}' is not configured or unknown.",
            )
        result = await service.sync_platform_range(
            body.platform,
            clients[body.platform],
            body.since,
            body.until,
            source=_PLATFORM_TO_SOURCE.get(body.platform, f"{body.platform}_API"),
        )
        return [result]

    results = []
    for name, client in clients.items():
        result = await service.sync_platform_range(
            name,
            client,
            body.since,
            body.until,
            source=_PLATFORM_TO_SOURCE.get(name, f"{name}_API"),
        )
        results.append(result)
    return results


@router.get("/sync/status", response_model=ReturnSyncStatusResponse)
async def sync_status(
    sync_repo: ReturnSyncStateRepository = Depends(get_return_sync_repo),
    record_repo: ReturnRecordRepository = Depends(get_return_record_repo),
):
    states = await sync_repo.get_all_states()
    counts_by_status = await record_repo.count_by_status()
    total_records = await record_repo.count()
    return ReturnSyncStatusResponse(
        platforms=[ReturnSyncStateResponse.model_validate(state) for state in states],
        total_records=total_records,
        counts_by_status=counts_by_status,
    )
