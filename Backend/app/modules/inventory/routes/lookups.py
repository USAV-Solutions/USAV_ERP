"""
Lookup tables API endpoints (Brand, Color, Condition, LCI Definition).
"""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models import Brand, Color, Condition, LCIDefinition, ProductFamily
from app.modules.inventory.schemas import (
    BrandCreate,
    BrandResponse,
    BrandUpdate,
    ColorCreate,
    ColorResponse,
    ColorUpdate,
    ConditionCreate,
    ConditionResponse,
    ConditionUpdate,
    LCIDefinitionCreate,
    LCIDefinitionResponse,
    LCIDefinitionUpdate,
    PaginatedResponse,
)


# ============================================================================
# BRAND ROUTER
# ============================================================================
brand_router = APIRouter(prefix="/brands", tags=["Brands"])


@brand_router.get("", response_model=PaginatedResponse)
async def list_brands(
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    search: Annotated[str | None, Query(description="Search by name")] = None,
    db: AsyncSession = Depends(get_db),
):
    """List all brands with optional search."""
    query = select(Brand)
    count_query = select(func.count()).select_from(Brand)
    
    if search:
        query = query.where(Brand.name.ilike(f"%{search}%"))
        count_query = count_query.where(Brand.name.ilike(f"%{search}%"))
    
    query = query.order_by(Brand.name).offset(skip).limit(limit)
    
    result = await db.execute(query)
    items = result.scalars().all()
    
    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0
    
    return PaginatedResponse(
        total=total,
        skip=skip,
        limit=limit,
        items=[BrandResponse.model_validate(item) for item in items]
    )


@brand_router.post("", response_model=BrandResponse, status_code=status.HTTP_201_CREATED)
async def create_brand(
    data: BrandCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new brand."""
    # Check for duplicate
    existing = await db.execute(select(Brand).where(Brand.name == data.name))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Brand '{data.name}' already exists"
        )
    
    brand = Brand(**data.model_dump())
    db.add(brand)
    await db.commit()
    await db.refresh(brand)
    return BrandResponse.model_validate(brand)


@brand_router.get("/{brand_id}", response_model=BrandResponse)
async def get_brand(brand_id: int, db: AsyncSession = Depends(get_db)):
    """Get a brand by ID."""
    result = await db.execute(select(Brand).where(Brand.id == brand_id))
    brand = result.scalar_one_or_none()
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found")
    return BrandResponse.model_validate(brand)


@brand_router.patch("/{brand_id}", response_model=BrandResponse)
async def update_brand(
    brand_id: int,
    data: BrandUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a brand."""
    result = await db.execute(select(Brand).where(Brand.id == brand_id))
    brand = result.scalar_one_or_none()
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found")
    
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(brand, key, value)
    
    await db.commit()
    await db.refresh(brand)
    return BrandResponse.model_validate(brand)


@brand_router.delete("/{brand_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_brand(brand_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a brand."""
    result = await db.execute(select(Brand).where(Brand.id == brand_id))
    brand = result.scalar_one_or_none()
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found")
    
    await db.delete(brand)
    await db.commit()


# ============================================================================
# COLOR ROUTER
# ============================================================================
color_router = APIRouter(prefix="/colors", tags=["Colors"])


@color_router.get("", response_model=PaginatedResponse)
async def list_colors(
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    search: Annotated[str | None, Query(description="Search by name or code")] = None,
    db: AsyncSession = Depends(get_db),
):
    """List all colors with optional search."""
    query = select(Color)
    count_query = select(func.count()).select_from(Color)
    
    if search:
        query = query.where(
            (Color.name.ilike(f"%{search}%")) | (Color.code.ilike(f"%{search}%"))
        )
        count_query = count_query.where(
            (Color.name.ilike(f"%{search}%")) | (Color.code.ilike(f"%{search}%"))
        )
    
    query = query.order_by(Color.name).offset(skip).limit(limit)
    
    result = await db.execute(query)
    items = result.scalars().all()
    
    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0
    
    return PaginatedResponse(
        total=total,
        skip=skip,
        limit=limit,
        items=[ColorResponse.model_validate(item) for item in items]
    )


@color_router.post("", response_model=ColorResponse, status_code=status.HTTP_201_CREATED)
async def create_color(
    data: ColorCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new color."""
    # Check for duplicate name or code
    existing_name = await db.execute(select(Color).where(Color.name == data.name))
    if existing_name.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Color with name '{data.name}' already exists"
        )
    
    existing_code = await db.execute(select(Color).where(Color.code == data.code.upper()))
    if existing_code.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Color with code '{data.code}' already exists"
        )
    
    color = Color(name=data.name, code=data.code.upper())
    db.add(color)
    await db.commit()
    await db.refresh(color)
    return ColorResponse.model_validate(color)


@color_router.get("/{color_id}", response_model=ColorResponse)
async def get_color(color_id: int, db: AsyncSession = Depends(get_db)):
    """Get a color by ID."""
    result = await db.execute(select(Color).where(Color.id == color_id))
    color = result.scalar_one_or_none()
    if not color:
        raise HTTPException(status_code=404, detail="Color not found")
    return ColorResponse.model_validate(color)


@color_router.delete("/{color_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_color(color_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a color."""
    result = await db.execute(select(Color).where(Color.id == color_id))
    color = result.scalar_one_or_none()
    if not color:
        raise HTTPException(status_code=404, detail="Color not found")
    
    await db.delete(color)
    await db.commit()


# ============================================================================
# CONDITION ROUTER
# ============================================================================
condition_router = APIRouter(prefix="/conditions", tags=["Conditions"])


@condition_router.get("", response_model=PaginatedResponse)
async def list_conditions(
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    db: AsyncSession = Depends(get_db),
):
    """List all conditions."""
    query = select(Condition).order_by(Condition.name).offset(skip).limit(limit)
    count_query = select(func.count()).select_from(Condition)
    
    result = await db.execute(query)
    items = result.scalars().all()
    
    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0
    
    return PaginatedResponse(
        total=total,
        skip=skip,
        limit=limit,
        items=[ConditionResponse.model_validate(item) for item in items]
    )


@condition_router.post("", response_model=ConditionResponse, status_code=status.HTTP_201_CREATED)
async def create_condition(
    data: ConditionCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new condition."""
    # Check for duplicate name or code
    existing_name = await db.execute(select(Condition).where(Condition.name == data.name))
    if existing_name.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Condition with name '{data.name}' already exists"
        )
    
    existing_code = await db.execute(select(Condition).where(Condition.code == data.code.upper()))
    if existing_code.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Condition with code '{data.code}' already exists"
        )
    
    condition = Condition(name=data.name, code=data.code.upper())
    db.add(condition)
    await db.commit()
    await db.refresh(condition)
    return ConditionResponse.model_validate(condition)


@condition_router.delete("/{condition_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_condition(condition_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a condition."""
    result = await db.execute(select(Condition).where(Condition.id == condition_id))
    condition = result.scalar_one_or_none()
    if not condition:
        raise HTTPException(status_code=404, detail="Condition not found")
    
    await db.delete(condition)
    await db.commit()


# ============================================================================
# LCI DEFINITION ROUTER
# ============================================================================
lci_router = APIRouter(prefix="/lci-definitions", tags=["LCI Definitions"])


@lci_router.get("", response_model=PaginatedResponse)
async def list_lci_definitions(
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    product_id: Annotated[int | None, Query(description="Filter by product ID")] = None,
    db: AsyncSession = Depends(get_db),
):
    """List all LCI definitions with optional product filter."""
    query = select(LCIDefinition)
    count_query = select(func.count()).select_from(LCIDefinition)
    
    if product_id is not None:
        query = query.where(LCIDefinition.product_id == product_id)
        count_query = count_query.where(LCIDefinition.product_id == product_id)
    
    query = query.order_by(LCIDefinition.product_id, LCIDefinition.lci_index).offset(skip).limit(limit)
    
    result = await db.execute(query)
    items = result.scalars().all()
    
    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0
    
    return PaginatedResponse(
        total=total,
        skip=skip,
        limit=limit,
        items=[LCIDefinitionResponse.model_validate(item) for item in items]
    )


@lci_router.post("", response_model=LCIDefinitionResponse, status_code=status.HTTP_201_CREATED)
async def create_lci_definition(
    data: LCIDefinitionCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new LCI definition. LCI index is auto-generated if not provided."""
    # Verify product family exists
    family_result = await db.execute(
        select(ProductFamily).where(ProductFamily.product_id == data.product_id)
    )
    if not family_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail=f"Product family {data.product_id} not found")
    
    # Auto-generate lci_index if not provided
    lci_index = data.lci_index
    if lci_index is None:
        max_result = await db.execute(
            select(func.max(LCIDefinition.lci_index))
            .where(LCIDefinition.product_id == data.product_id)
        )
        max_lci = max_result.scalar() or 0
        lci_index = max_lci + 1
    
    if lci_index > 99:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="LCI index cannot exceed 99"
        )
    
    # Check for duplicate
    existing = await db.execute(
        select(LCIDefinition).where(
            (LCIDefinition.product_id == data.product_id) &
            (LCIDefinition.lci_index == lci_index)
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"LCI {lci_index} already exists for product {data.product_id}"
        )
    
    lci_def = LCIDefinition(
        product_id=data.product_id,
        lci_index=lci_index,
        component_name=data.component_name
    )
    db.add(lci_def)
    await db.commit()
    await db.refresh(lci_def)
    return LCIDefinitionResponse.model_validate(lci_def)


@lci_router.get("/{lci_id}", response_model=LCIDefinitionResponse)
async def get_lci_definition(lci_id: int, db: AsyncSession = Depends(get_db)):
    """Get an LCI definition by ID."""
    result = await db.execute(select(LCIDefinition).where(LCIDefinition.id == lci_id))
    lci_def = result.scalar_one_or_none()
    if not lci_def:
        raise HTTPException(status_code=404, detail="LCI definition not found")
    return LCIDefinitionResponse.model_validate(lci_def)


@lci_router.patch("/{lci_id}", response_model=LCIDefinitionResponse)
async def update_lci_definition(
    lci_id: int,
    data: LCIDefinitionUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update an LCI definition (only component name can be updated)."""
    result = await db.execute(select(LCIDefinition).where(LCIDefinition.id == lci_id))
    lci_def = result.scalar_one_or_none()
    if not lci_def:
        raise HTTPException(status_code=404, detail="LCI definition not found")
    
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(lci_def, key, value)
    
    await db.commit()
    await db.refresh(lci_def)
    return LCIDefinitionResponse.model_validate(lci_def)


@lci_router.delete("/{lci_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lci_definition(lci_id: int, db: AsyncSession = Depends(get_db)):
    """Delete an LCI definition."""
    result = await db.execute(select(LCIDefinition).where(LCIDefinition.id == lci_id))
    lci_def = result.scalar_one_or_none()
    if not lci_def:
        raise HTTPException(status_code=404, detail="LCI definition not found")
    
    await db.delete(lci_def)
    await db.commit()
