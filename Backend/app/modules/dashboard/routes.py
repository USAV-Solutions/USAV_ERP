"""Best-selling products dashboard API routes."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.core.database import get_db
from app.models import UserRole
from app.modules.dashboard.schemas import (
    BestSellingProductDetail,
    BestSellingProductsResponse,
    BestSellingSummary,
    PlatformBreakdownRow,
    TrendPoint,
)
from app.modules.dashboard.service import BestSellingDashboardService, SortBy, SortDir
from app.modules.orders.models import OrderPlatform


router = APIRouter(
    prefix="/dashboard/best-selling",
    tags=["Best Selling Dashboard"],
    dependencies=[Depends(require_roles(UserRole.ADMIN, UserRole.SALES_REP, UserRole.ACCOUNTANT, UserRole.WAREHOUSE_OP))],
)


def get_dashboard_service(db: AsyncSession = Depends(get_db)) -> BestSellingDashboardService:
    return BestSellingDashboardService(db)


@router.get("/summary", response_model=BestSellingSummary)
async def best_selling_summary(
    service: Annotated[BestSellingDashboardService, Depends(get_dashboard_service)],
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
    platform: Annotated[OrderPlatform | None, Query()] = None,
) -> BestSellingSummary:
    return await service.summary(start_date=start_date, end_date=end_date, platform=platform)


@router.get("/products", response_model=BestSellingProductsResponse)
async def best_selling_products(
    service: Annotated[BestSellingDashboardService, Depends(get_dashboard_service)],
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
    platform: Annotated[OrderPlatform | None, Query()] = None,
    search: Annotated[str | None, Query()] = None,
    sort_by: Annotated[SortBy, Query()] = "qty_sold",
    sort_dir: Annotated[SortDir, Query()] = "desc",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> BestSellingProductsResponse:
    return await service.products(
        start_date=start_date,
        end_date=end_date,
        platform=platform,
        search=search,
        sort_by=sort_by,
        sort_dir=sort_dir,
        limit=limit,
        offset=offset,
    )


@router.get("/trends", response_model=list[TrendPoint])
async def best_selling_trends(
    service: Annotated[BestSellingDashboardService, Depends(get_dashboard_service)],
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
    platform: Annotated[OrderPlatform | None, Query()] = None,
    sku: Annotated[str | None, Query()] = None,
) -> list[TrendPoint]:
    return await service.trends(start_date=start_date, end_date=end_date, platform=platform, sku=sku)


@router.get("/platform-breakdown", response_model=list[PlatformBreakdownRow])
async def best_selling_platform_breakdown(
    service: Annotated[BestSellingDashboardService, Depends(get_dashboard_service)],
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
    sku: Annotated[str | None, Query()] = None,
) -> list[PlatformBreakdownRow]:
    return await service.platform_breakdown(start_date=start_date, end_date=end_date, sku=sku)


@router.get("/products/{sku}", response_model=BestSellingProductDetail)
async def best_selling_product_detail(
    sku: str,
    service: Annotated[BestSellingDashboardService, Depends(get_dashboard_service)],
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
) -> BestSellingProductDetail:
    detail = await service.product_detail(sku=sku, start_date=start_date, end_date=end_date)
    if not detail:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SKU not found in selected date range")
    return detail

