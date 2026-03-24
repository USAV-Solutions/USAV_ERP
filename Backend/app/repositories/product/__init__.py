"""
Product-related repositories.
Handles database operations for ProductFamily, ProductIdentity, and ProductVariant.
"""
import hashlib
from typing import Any, Optional, Sequence

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    IdentityType,
    ProductFamily,
    ProductIdentity,
    ProductVariant,
    ZohoSyncStatus,
)
from app.repositories.base import BaseRepository


class ProductFamilyRepository(BaseRepository[ProductFamily]):
    """Repository for ProductFamily operations."""
    
    def __init__(self, session: AsyncSession):
        super().__init__(ProductFamily, session)
    
    async def get_max_product_id(self) -> Optional[int]:
        """Get the maximum product_id currently in use."""
        stmt = select(func.max(ProductFamily.product_id))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
    
    async def get_with_identities(self, product_id: int) -> Optional[ProductFamily]:
        """Get a ProductFamily with all its identities loaded."""
        stmt = (
            select(ProductFamily)
            .options(selectinload(ProductFamily.identities))
            .where(ProductFamily.product_id == product_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
    
    async def search_by_name(
        self,
        query: str,
        skip: int = 0,
        limit: int = 100
    ) -> Sequence[ProductFamily]:
        """Search families by name or product_id (case-insensitive)."""
        pattern = f"%{query}%"
        stmt = (
            select(ProductFamily)
            .where(
                or_(
                    ProductFamily.base_name.ilike(pattern),
                    cast(ProductFamily.product_id, String).ilike(pattern),
                )
            )
            .order_by(ProductFamily.product_id)
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()


class ProductIdentityRepository(BaseRepository[ProductIdentity]):
    """Repository for ProductIdentity operations."""
    
    def __init__(self, session: AsyncSession):
        super().__init__(ProductIdentity, session)
    
    async def get_by_upis_h(self, upis_h: str) -> Optional[ProductIdentity]:
        """Get identity by generated UPIS-H string."""
        return await self.get_by_field("generated_upis_h", upis_h)
    
    async def get_with_variants(self, id: int) -> Optional[ProductIdentity]:
        """Get identity with all variants loaded."""
        stmt = (
            select(ProductIdentity)
            .options(selectinload(ProductIdentity.variants))
            .where(ProductIdentity.id == id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
    
    async def get_by_family(
        self,
        product_id: int,
        skip: int = 0,
        limit: int = 100
    ) -> Sequence[ProductIdentity]:
        """Get all identities for a product family."""
        stmt = (
            select(ProductIdentity)
            .where(ProductIdentity.product_id == product_id)
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()
    
    async def get_next_lci(self, product_id: int) -> int:
        """Get the next available LCI for a product family."""
        stmt = (
            select(func.coalesce(func.max(ProductIdentity.lci), 0) + 1)
            .where(ProductIdentity.product_id == product_id)
            .where(ProductIdentity.type == IdentityType.P)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()
    
    def generate_upis_h(
        self,
        product_id: int,
        identity_type: IdentityType,
        lci: Optional[int]
    ) -> str:
        """Generate UPIS-H string from identity components."""
        product_id_str = f"{product_id:05d}"
        
        if identity_type == IdentityType.PRODUCT:
            return product_id_str
        elif identity_type == IdentityType.P and lci is not None:
            return f"{product_id_str}-{identity_type.value}-{lci}"
        else:
            return f"{product_id_str}-{identity_type.value}"
    
    def generate_hex_signature(
        self,
        product_id: int,
        identity_type: IdentityType,
        lci: Optional[int]
    ) -> str:
        """Generate 32-bit HEX signature from identity components."""
        # Create a deterministic string from identity components
        identity_string = f"{product_id:05d}|{identity_type.value}|{lci or ''}"
        
        # Generate SHA-256 and take first 8 hex chars (32 bits)
        hash_bytes = hashlib.sha256(identity_string.encode()).digest()
        return hash_bytes[:4].hex().upper()
    
    async def create_identity(self, data: dict[str, Any]) -> ProductIdentity:
        """Create a new identity with auto-generated UPIS-H and hex signature."""
        product_id = data["product_id"]
        identity_type = data["type"]
        lci = data.get("lci")
        
        # Auto-generate UPIS-H
        data["generated_upis_h"] = self.generate_upis_h(product_id, identity_type, lci)
        
        # Auto-generate hex signature
        data["hex_signature"] = self.generate_hex_signature(product_id, identity_type, lci)
        
        return await self.create(data)


class ProductVariantRepository(BaseRepository[ProductVariant]):
    """Repository for ProductVariant operations."""
    
    def __init__(self, session: AsyncSession):
        super().__init__(ProductVariant, session)
    
    async def get_by_sku(self, full_sku: str) -> Optional[ProductVariant]:
        """Get variant by full SKU string."""
        return await self.get_by_field("full_sku", full_sku)
    
    async def get_by_zoho_id(self, zoho_item_id: str) -> Optional[ProductVariant]:
        """Get variant by Zoho item ID."""
        return await self.get_by_field("zoho_item_id", zoho_item_id)
    
    async def get_by_identity(
        self,
        identity_id: int,
        include_inactive: bool = False,
        skip: int = 0,
        limit: int = 100
    ) -> Sequence[ProductVariant]:
        """Get all variants for an identity."""
        stmt = (
            select(ProductVariant)
            .where(ProductVariant.identity_id == identity_id)
        )
        
        if not include_inactive:
            stmt = stmt.where(ProductVariant.is_active == True)
        
        stmt = stmt.offset(skip).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()
    
    async def get_pending_zoho_sync(
        self,
        limit: int = 100
    ) -> Sequence[ProductVariant]:
        """Get variants pending Zoho sync."""
        stmt = (
            select(ProductVariant)
            .where(ProductVariant.zoho_sync_status.in_([
                ZohoSyncStatus.PENDING,
                ZohoSyncStatus.DIRTY
            ]))
            .where(ProductVariant.is_active == True)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()
    
    async def get_with_listings(self, id: int) -> Optional[ProductVariant]:
        """Get variant with all platform listings loaded."""
        stmt = (
            select(ProductVariant)
            .options(selectinload(ProductVariant.listings))
            .where(ProductVariant.id == id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
    
    def generate_full_sku(
        self,
        upis_h: str,
        color_code: Optional[str],
        condition_code: Optional[str]
    ) -> str:
        """Generate full SKU from components."""
        parts = [upis_h]
        
        if color_code:
            parts.append(color_code.upper())
        
        if condition_code:
            parts.append(condition_code)
        
        return "-".join(parts)
    
    async def create_variant(
        self,
        data: dict[str, Any],
        identity: ProductIdentity
    ) -> ProductVariant:
        """Create a new variant with auto-generated full SKU."""
        color_code = data.get("color_code")
        condition_code = data.get("condition_code")
        
        # Handle enum value
        if condition_code and hasattr(condition_code, "value"):
            condition_str = condition_code.value
        else:
            condition_str = condition_code
        
        # Auto-generate full SKU
        data["full_sku"] = self.generate_full_sku(
            identity.generated_upis_h,
            color_code,
            condition_str
        )
        
        return await self.create(data)


__all__ = [
    "ProductFamilyRepository",
    "ProductIdentityRepository",
    "ProductVariantRepository",
]
