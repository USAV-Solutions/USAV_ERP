"""
SQLAlchemy models for USAV Inventory Database.
Implements the Two-Layer Identification Model from the SKU Specification.
"""
import enum
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from typing import List


# ============================================================================
# ENUMS
# ============================================================================

class IdentityType(str, enum.Enum):
    """Product identity types as defined in SKU spec."""
    PRODUCT = "Product"  # Standard product
    B = "B"              # Bundle
    P = "P"              # Part
    K = "K"              # Kit


class PhysicalClass(str, enum.Enum):
    """Physical classification registry codes."""
    E = "E"  # Electronics
    C = "C"  # Cover/Case
    P = "P"  # Peripheral
    S = "S"  # Speaker
    W = "W"  # Wire/Cable
    A = "A"  # Accessory


class ConditionCode(str, enum.Enum):
    """Product condition codes."""
    N = "N"  # New
    R = "R"  # Refurbished/Repair
    # NULL = Used (default)


class ZohoSyncStatus(str, enum.Enum):
    """Synchronization status with Zoho."""
    PENDING = "PENDING"
    SYNCED = "SYNCED"
    ERROR = "ERROR"
    DIRTY = "DIRTY"


class PlatformSyncStatus(str, enum.Enum):
    """Synchronization status for platform listings."""
    PENDING = "PENDING"
    SYNCED = "SYNCED"
    ERROR = "ERROR"


class InventoryStatus(str, enum.Enum):
    """Status of physical inventory items."""
    AVAILABLE = "AVAILABLE"
    SOLD = "SOLD"
    RESERVED = "RESERVED"
    RMA = "RMA"
    DAMAGED = "DAMAGED"


class BundleRole(str, enum.Enum):
    """Role of a component within a bundle."""
    PRIMARY = "Primary"
    ACCESSORY = "Accessory"
    SATELLITE = "Satellite"


class Platform(str, enum.Enum):
    """Supported sales platforms."""
    AMAZON = "AMAZON"
    EBAY_MEKONG = "EBAY_MEKONG"
    EBAY_USAV = "EBAY_USAV"
    EBAY_DRAGON = "EBAY_DRAGON"
    ECWID = "ECWID"


# ============================================================================
# MIXINS
# ============================================================================

class TimestampMixin:
    """Mixin for created_at and updated_at timestamps."""
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# ============================================================================
# LOOKUP TABLES
# ============================================================================

class Brand(Base, TimestampMixin):
    """
    Brand/Manufacturer lookup table.
    Allows users to manage a list of brands for products.
    """
    __tablename__ = "brand"
    
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        unique=True,
        comment="Brand name (e.g., 'Bose', 'USAV Solutions').",
    )
    
    def __repr__(self) -> str:
        return f"<Brand(id={self.id}, name='{self.name}')>"


class Color(Base, TimestampMixin):
    """
    Color lookup table.
    Stores color names with their associated codes.
    """
    __tablename__ = "color"
    
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    name: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Color name (e.g., 'Black', 'White').",
    )
    code: Mapped[str] = mapped_column(
        String(2),
        nullable=False,
        unique=True,
        comment="Color code (e.g., 'BK', 'WY').",
    )
    
    __table_args__ = (
        UniqueConstraint("name", name="uq_color_name"),
    )
    
    def __repr__(self) -> str:
        return f"<Color(id={self.id}, name='{self.name}', code='{self.code}')>"


class Condition(Base, TimestampMixin):
    """
    Condition lookup table.
    Stores condition names with their associated codes.
    """
    __tablename__ = "condition"
    
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    name: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Condition name (e.g., 'Used', 'New').",
    )
    code: Mapped[str] = mapped_column(
        String(1),
        nullable=False,
        unique=True,
        comment="Condition code (e.g., 'U', 'N').",
    )
    
    __table_args__ = (
        UniqueConstraint("name", name="uq_condition_name"),
    )
    
    def __repr__(self) -> str:
        return f"<Condition(id={self.id}, name='{self.name}', code='{self.code}')>"


class LCIDefinition(Base, TimestampMixin):
    """
    Local Component Index (LCI) definition table.
    Maps LCI numbers to component names for each product family.
    """
    __tablename__ = "lci_definition"
    
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    product_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("product_family.product_id", ondelete="CASCADE"),
        nullable=False,
        comment="Links to Product Family.",
    )
    lci_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="LCI number (1-99).",
    )
    component_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Component name (e.g., 'Motherboard', 'Power Supply').",
    )
    
    __table_args__ = (
        UniqueConstraint("product_id", "lci_index", name="uq_lci_product_index"),
        CheckConstraint(
            "lci_index >= 1 AND lci_index <= 99",
            name="ck_lci_index_range",
        ),
        Index("ix_lci_product_id", "product_id"),
    )
    
    def __repr__(self) -> str:
        return f"<LCIDefinition(product_id={self.product_id}, lci={self.lci_index}, name='{self.component_name}')>"


# ============================================================================
# CORE PRODUCT TABLES
# ============================================================================

class ProductFamily(Base, TimestampMixin):
    """
    High-level product grouping.
    The 5-digit ECWID ID acts as the namespace root for all related identities.
    """
    __tablename__ = "product_family"
    
    product_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        comment="The 5-digit ECWID ID (e.g., 00845). Acts as namespace root.",
    )
    base_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Human-readable name (e.g., 'Bose 201 Series').",
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Optional detailed description.",
    )
    brand_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("brand.id", ondelete="SET NULL"),
        nullable=True,
        comment="Links to Brand.",
    )
    dimension_length: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2),
        nullable=True,
        comment="Product length in inches.",
    )
    dimension_width: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2),
        nullable=True,
        comment="Product width in inches.",
    )
    dimension_height: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2),
        nullable=True,
        comment="Product height in inches.",
    )
    weight: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2),
        nullable=True,
        comment="Product weight in pounds.",
    )
    kit_included_products: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Comma-separated list of included products for Kit type.",
    )
    
    # Relationships
    brand: Mapped[Optional["Brand"]] = relationship(
        "Brand",
        lazy="selectin",
    )
    identities: Mapped["List[ProductIdentity]"] = relationship(
        "ProductIdentity",
        back_populates="family",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    lci_definitions: Mapped["List[LCIDefinition]"] = relationship(
        "LCIDefinition",
        backref="family",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    
    __table_args__ = (
        CheckConstraint(
            "product_id >= 0 AND product_id <= 99999",
            name="ck_product_family_id_range",
        ),
        Index("ix_product_family_brand", "brand_id"),
    )
    
    def __repr__(self) -> str:
        return f"<ProductFamily(product_id={self.product_id:05d}, name='{self.base_name}')>"


class ProductIdentity(Base, TimestampMixin):
    """
    Layer 1: Product Identity (The "Engineering" Layer).
    Defines WHAT an item IS. This data is immutable once created.
    Implements UPIS-H (Unique Product Identity Signature - Human Readable).
    """
    __tablename__ = "product_identity"
    
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    product_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("product_family.product_id", ondelete="CASCADE"),
        nullable=False,
        comment="Links to Family.",
    )
    type: Mapped[IdentityType] = mapped_column(
        Enum(IdentityType, name="identity_type_enum", values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        comment="Product (standard), B (Bundle), P (Part), K (Kit).",
    )
    lci: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Local Component Index (1-99). NULL unless Type=P.",
    )
    physical_class: Mapped[Optional[PhysicalClass]] = mapped_column(
        Enum(PhysicalClass, name="physical_class_enum"),
        nullable=True,
        comment="Registry Code: E (Electronics), C (Cover), etc.",
    )
    generated_upis_h: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        unique=True,
        comment="Computed identity string (e.g., '00845-P-1').",
    )
    hex_signature: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
        comment="32-bit HEX encoding. IMMUTABLE after creation.",
    )
    
    # Relationships
    family: Mapped["ProductFamily"] = relationship(
        "ProductFamily",
        back_populates="identities",
    )
    variants: Mapped["List[ProductVariant]"] = relationship(
        "ProductVariant",
        back_populates="identity",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    # Bundle relationships (as parent)
    bundle_children: Mapped["List[BundleComponent]"] = relationship(
        "BundleComponent",
        foreign_keys="BundleComponent.parent_identity_id",
        back_populates="parent",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    # Bundle relationships (as child/component)
    bundle_parents: Mapped["List[BundleComponent]"] = relationship(
        "BundleComponent",
        foreign_keys="BundleComponent.child_identity_id",
        back_populates="child",
        lazy="selectin",
    )
    
    __table_args__ = (
        # LCI must be unique within a product family for type=P
        UniqueConstraint(
            "product_id", "type", "lci",
            name="uq_identity_product_type_lci",
        ),
        # LCI must be between 1-99 when present
        CheckConstraint(
            "(lci IS NULL) OR (lci >= 1 AND lci <= 99)",
            name="ck_identity_lci_range",
        ),
        # LCI must be NULL for non-Part types
        CheckConstraint(
            "(type = 'P' AND lci IS NOT NULL) OR (type != 'P' AND lci IS NULL)",
            name="ck_identity_lci_type_constraint",
        ),
        Index("ix_identity_product_id", "product_id"),
        Index("ix_identity_hex_signature", "hex_signature"),
    )
    
    def __repr__(self) -> str:
        return f"<ProductIdentity(id={self.id}, upis_h='{self.generated_upis_h}')>"


class ProductVariant(Base, TimestampMixin):
    """
    Layer 2: Product Variant (The "Sales" Layer).
    Defines sellable configurations (Color, Condition) of an Identity.
    """
    __tablename__ = "product_variant"
    
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    identity_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("product_identity.id", ondelete="CASCADE"),
        nullable=False,
        comment="Links to the immutable Identity.",
    )
    color_code: Mapped[Optional[str]] = mapped_column(
        String(2),
        nullable=True,
        comment="BK, WY, SV (See Color Index in Spec).",
    )
    condition_code: Mapped[Optional[ConditionCode]] = mapped_column(
        Enum(ConditionCode, name="condition_code_enum"),
        nullable=True,
        comment="N (New), R (Repair), or NULL (Used/Default).",
    )
    full_sku: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        unique=True,
        comment="Complete sellable string (e.g., '00845-P-1-WY-N').",
    )
    zoho_item_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="Item ID on Zoho Inventory System.",
    )
    zoho_sync_status: Mapped[ZohoSyncStatus] = mapped_column(
        Enum(ZohoSyncStatus, name="zoho_sync_status_enum"),
        nullable=False,
        default=ZohoSyncStatus.PENDING,
        comment="Sync status with Zoho.",
    )
    zoho_last_synced_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Last successful sync timestamp.",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="Soft-delete flag for discontinued variants.",
    )
    
    # Relationships
    identity: Mapped["ProductIdentity"] = relationship(
        "ProductIdentity",
        back_populates="variants",
    )
    listings: Mapped["List[PlatformListing]"] = relationship(
        "PlatformListing",
        back_populates="variant",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    inventory_items: Mapped["List[InventoryItem]"] = relationship(
        "InventoryItem",
        back_populates="variant",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    
    __table_args__ = (
        # Variant must be unique per identity + color + condition
        UniqueConstraint(
            "identity_id", "color_code", "condition_code",
            name="uq_variant_identity_color_condition",
        ),
        Index("ix_variant_identity_id", "identity_id"),
        Index("ix_variant_zoho_item_id", "zoho_item_id"),
        Index("ix_variant_zoho_sync_status", "zoho_sync_status"),
        Index("ix_variant_is_active", "is_active"),
    )
    
    def __repr__(self) -> str:
        return f"<ProductVariant(id={self.id}, sku='{self.full_sku}')>"


# ============================================================================
# COMPOSITION TABLES
# ============================================================================

class BundleComponent(Base, TimestampMixin):
    """
    Bill of Materials for Bundles and Kits.
    Links to Identity, not Variant (the recipe is identity-level).
    """
    __tablename__ = "bundle_component"
    
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    parent_identity_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("product_identity.id", ondelete="CASCADE"),
        nullable=False,
        comment="The Bundle/Kit Identity (e.g., '02391-B').",
    )
    child_identity_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("product_identity.id", ondelete="CASCADE"),
        nullable=False,
        comment="The Component Identity (e.g., '00845').",
    )
    quantity_required: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        comment="How many of this component are needed.",
    )
    role: Mapped[BundleRole] = mapped_column(
        Enum(BundleRole, name="bundle_role_enum"),
        nullable=False,
        default=BundleRole.PRIMARY,
        comment="Context: Primary, Accessory, Satellite.",
    )
    
    # Relationships
    parent: Mapped["ProductIdentity"] = relationship(
        "ProductIdentity",
        foreign_keys=[parent_identity_id],
        back_populates="bundle_children",
    )
    child: Mapped["ProductIdentity"] = relationship(
        "ProductIdentity",
        foreign_keys=[child_identity_id],
        back_populates="bundle_parents",
    )
    
    __table_args__ = (
        # Prevent duplicate parent-child pairs
        UniqueConstraint(
            "parent_identity_id", "child_identity_id",
            name="uq_bundle_parent_child",
        ),
        # Prevent self-referencing bundles
        CheckConstraint(
            "parent_identity_id != child_identity_id",
            name="ck_bundle_no_self_reference",
        ),
        CheckConstraint(
            "quantity_required > 0",
            name="ck_bundle_positive_quantity",
        ),
        Index("ix_bundle_parent_id", "parent_identity_id"),
        Index("ix_bundle_child_id", "child_identity_id"),
    )
    
    def __repr__(self) -> str:
        return f"<BundleComponent(parent={self.parent_identity_id}, child={self.child_identity_id}, qty={self.quantity_required})>"


# ============================================================================
# EXTERNAL SYNC TABLES
# ============================================================================

class PlatformListing(Base, TimestampMixin):
    """
    Manages the "Outbox" for syncing to external platforms.
    Tracks the listing state for each variant on each platform.
    """
    __tablename__ = "platform_listing"
    
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    variant_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("product_variant.id", ondelete="CASCADE"),
        nullable=False,
        comment="The specific item being sold.",
    )
    platform: Mapped[Platform] = mapped_column(
        Enum(Platform, name="platform_enum"),
        nullable=False,
        comment="ZOHO, AMAZON_US, EBAY, etc.",
    )
    external_ref_id: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="The ID on the remote platform (Zoho Item ID, ASIN).",
    )
    listed_name: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        comment="The product name as displayed on this platform.",
    )
    listed_description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="The product description as displayed on this platform.",
    )
    listing_price: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2),
        nullable=True,
        comment="The specific price for this platform.",
    )
    sync_status: Mapped[PlatformSyncStatus] = mapped_column(
        Enum(PlatformSyncStatus, name="platform_sync_status_enum"),
        nullable=False,
        default=PlatformSyncStatus.PENDING,
        comment="PENDING (needs push), SYNCED (clean), ERROR (retrying).",
    )
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Last successful sync timestamp.",
    )
    sync_error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Error message from last failed sync attempt.",
    )
    platform_metadata: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Platform-specific fields (Amazon Bullet Points, eBay Category ID).",
    )
    
    # Relationships
    variant: Mapped["ProductVariant"] = relationship(
        "ProductVariant",
        back_populates="listings",
    )
    
    __table_args__ = (
        # One listing per variant per platform
        UniqueConstraint(
            "variant_id", "platform",
            name="uq_listing_variant_platform",
        ),
        Index("ix_listing_variant_id", "variant_id"),
        Index("ix_listing_platform", "platform"),
        Index("ix_listing_sync_status", "sync_status"),
        Index("ix_listing_external_ref", "platform", "external_ref_id"),
    )
    
    def __repr__(self) -> str:
        return f"<PlatformListing(id={self.id}, variant={self.variant_id}, platform={self.platform.value})>"


# ============================================================================
# INVENTORY TABLES
# ============================================================================

class InventoryItem(Base, TimestampMixin):
    """
    Tracks specific physical instances of products.
    Each row represents a single physical unit with its own serial number and cost basis.
    """
    __tablename__ = "inventory_item"
    
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    serial_number: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        unique=True,
        comment="Manufacturer serial (if applicable).",
    )
    variant_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("product_variant.id", ondelete="CASCADE"),
        nullable=False,
        comment="Links to what this item IS.",
    )
    status: Mapped[InventoryStatus] = mapped_column(
        Enum(InventoryStatus, name="inventory_status_enum"),
        nullable=False,
        default=InventoryStatus.AVAILABLE,
        comment="AVAILABLE, SOLD, RESERVED, RMA, DAMAGED.",
    )
    location_code: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="Warehouse location (e.g., 'A1-S2').",
    )
    cost_basis: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2),
        nullable=True,
        comment="Exact acquisition cost (for accounting/COGS).",
    )
    notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Additional notes about this specific item.",
    )
    received_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When this item was received into inventory.",
    )
    sold_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When this item was sold (if applicable).",
    )
    
    # Relationships
    variant: Mapped["ProductVariant"] = relationship(
        "ProductVariant",
        back_populates="inventory_items",
    )
    
    __table_args__ = (
        CheckConstraint(
            "cost_basis IS NULL OR cost_basis >= 0",
            name="ck_inventory_positive_cost",
        ),
        Index("ix_inventory_variant_id", "variant_id"),
        Index("ix_inventory_status", "status"),
        Index("ix_inventory_location", "location_code"),
        # Composite index for common query: find available items of a variant
        Index("ix_inventory_variant_status", "variant_id", "status"),
    )
    
    def __repr__(self) -> str:
        return f"<InventoryItem(id={self.id}, serial='{self.serial_number}', status={self.status.value})>"
