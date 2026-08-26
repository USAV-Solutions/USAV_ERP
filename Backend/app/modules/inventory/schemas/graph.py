"""
Graph, Orbit, and AI Matching Schemas for Listing Management.
"""
import enum
from datetime import datetime
from typing import Any, Optional, List, Dict
from pydantic import BaseModel, ConfigDict, Field

from app.models import Platform, PlatformSyncStatus


class RelationshipType(str, enum.Enum):
    """Semantic relationship types between catalog entities and listings."""
    EXACT = "EXACT"                          # Direct 1:1 listing of physical product
    ACCESSORY = "ACCESSORY"                  # Compatible accessory (e.g. bluetooth adapter, bracket, cable)
    BUNDLE_COMPONENT = "BUNDLE_COMPONENT"    # Dynamic USAV Bundle component (Type B)
    KIT_COMPONENT = "KIT_COMPONENT"          # Predefined manufacturer kit component (Type K)
    PART_LCI = "PART_LCI"                    # Internal LCI replacement part (Type P)
    SIBLING_VARIANT = "SIBLING_VARIANT"      # Sibling variant under same identity / family
    # Backward compatibility aliases
    BUNDLE = "BUNDLE"
    PART = "PART"
    RELATED_PRODUCT = "RELATED_PRODUCT"


class StockWarningStatus(str, enum.Enum):
    """Stock runway warning levels."""
    HEALTHY = "HEALTHY"          # > 30 days runway
    LOW_STOCK = "LOW_STOCK"      # < 14 days runway
    OUT_OF_STOCK = "OUT_OF_STOCK" # 0 units available with active sales demand


class ProductNode(BaseModel):
    """Central product variant node in the knowledge graph."""
    variant_id: int
    full_sku: str
    variant_name: Optional[str] = None
    thumbnail_url: Optional[str] = None
    identity_name: Optional[str] = None
    family_name: Optional[str] = None
    family_code: Optional[str] = None
    condition_code: Optional[str] = None
    color_code: Optional[str] = None
    identity_type: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class ListingNode(BaseModel):
    """Platform listing node in the knowledge graph."""
    listing_id: int
    variant_id: Optional[int] = None
    platform: Platform
    external_ref_id: Optional[str] = None
    merchant_sku: Optional[str] = None
    listed_name: Optional[str] = None
    listing_price: Optional[float] = None
    listing_quantity: Optional[int] = None
    sync_status: PlatformSyncStatus = PlatformSyncStatus.PENDING
    relationship_type: RelationshipType = RelationshipType.EXACT
    last_synced_at: Optional[datetime] = None
    sync_error_message: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class GraphEdge(BaseModel):
    """Edge connecting product and listing nodes."""
    source: str
    target: str
    relationship: str = "listed_on"
    relationship_type: RelationshipType = RelationshipType.EXACT
    confidence: Optional[float] = None


class GroupHub(BaseModel):
    """A logical group hub node (Variants, Accessory, Component, Bundle)."""
    hub_id: str           # e.g. "hub-variants", "hub-accessory", "hub-component"
    hub_label: str        # "Variants", "Accessory", "Component"
    hub_type: str         # "variants", "accessory", "component", "bundle"
    children_ids: List[str] = Field(default_factory=list)


class GraphTopologyResponse(BaseModel):
    """Full graph topology for visualizer canvas."""
    product: ProductNode
    listings: List[ListingNode] = Field(default_factory=list)
    related_products: List[ProductNode] = Field(default_factory=list)
    edges: List[GraphEdge] = Field(default_factory=list)
    hubs: List[GroupHub] = Field(default_factory=list)


class AISuggestRequest(BaseModel):
    """Request for AI listing match suggestions."""
    variant_id: int = Field(..., ge=1, description="Target product variant ID")
    platforms: Optional[List[Platform]] = Field(None, description="Filter by platforms")
    limit: int = Field(default=10, ge=1, le=50, description="Max suggestions to return")
    include_linked: bool = Field(default=False, description="Whether to include listings already linked to other variants")


class AISuggestion(BaseModel):
    """Single candidate suggestion with confidence score and relationship type."""
    listing_id: int
    platform: Platform
    external_ref_id: Optional[str] = None
    merchant_sku: Optional[str] = None
    listed_name: Optional[str] = None
    listing_price: Optional[float] = None
    relationship_type: RelationshipType = RelationshipType.EXACT
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score from 0.0 to 1.0")
    reasons: List[str] = Field(default_factory=list, description="Reasons explaining the match confidence")


class AISuggestResponse(BaseModel):
    """Response containing AI-suggested listing candidates."""
    variant_id: int
    variant_sku: str
    variant_name: Optional[str] = None
    suggestions: List[AISuggestion]


class LockRelationshipRequest(BaseModel):
    """Request to lock a listing to a product variant."""
    listing_id: int = Field(..., ge=1, description="Platform listing ID")
    variant_id: int = Field(..., ge=1, description="Product variant ID to link")
    relationship_type: RelationshipType = Field(default=RelationshipType.EXACT, description="Type of relationship")
    enrich_metadata: bool = Field(default=True, description="Enrich empty variant fields from listing")


class LockRelationshipResponse(BaseModel):
    """Confirmation of locked relationship."""
    success: bool
    listing_id: int
    variant_id: int
    platform: Platform
    relationship_type: RelationshipType
    enriched_fields: List[str]
    message: str


class CompareRequest(BaseModel):
    """Request to compare 2 or more listing nodes."""
    listing_ids: List[int] = Field(..., min_length=2, max_length=10, description="List of 2 to 10 listing IDs to compare")


class CompareField(BaseModel):
    """Comparison metric row."""
    key: str
    label: str
    values: Dict[str, Any]


class CompareResponse(BaseModel):
    """Side-by-side comparison response."""
    listing_ids: List[int]
    listings: List[ListingNode]
    comparison_fields: List[CompareField]


# ============================================================================
# ORBIT VIEW & ANALYTICS SCHEMAS
# ============================================================================

class PriceMismatchAlert(BaseModel):
    """Ecwid vs. Shopify price mismatch detection."""
    has_mismatch: bool = False
    ecwid_price: Optional[float] = None
    shopify_price: Optional[float] = None
    price_diff: Optional[float] = None
    message: Optional[str] = None


class ChannelSalesMetric(BaseModel):
    """Channel breakdown of sales orders."""
    platform: str
    units_sold_30d: int = 0
    revenue_30d: float = 0.0
    units_sold_90d: int = 0
    revenue_90d: float = 0.0


class OrbitAnalyticsResponse(BaseModel):
    """Sales velocity, order metrics, stock runway, and price mismatch alert."""
    variant_id: int
    full_sku: str
    units_sold_30d: int = 0
    revenue_30d: float = 0.0
    units_sold_90d: int = 0
    revenue_90d: float = 0.0
    monthly_velocity: float = 0.0
    available_stock: int = 0
    runway_days: Optional[float] = None
    stock_warning: StockWarningStatus = StockWarningStatus.HEALTHY
    price_mismatch: PriceMismatchAlert = Field(default_factory=PriceMismatchAlert)
    channel_metrics: List[ChannelSalesMetric] = Field(default_factory=list)


class BundleComponentInput(BaseModel):
    """Input component for Kit / Bundle formation."""
    child_variant_id: int
    quantity_required: int = Field(default=1, ge=1)
    role: str = Field(default="PRIMARY", description="PRIMARY, ACCESSORY, SATELLITE, SUBWOOFER, MAIN_UNIT")


class OrbitCreateBundleKitRequest(BaseModel):
    """Request to form a Bundle (Type B) or Kit (Type K) per USAV UPIS spec."""
    type: str = Field(..., description="'B' for USAV Bundle, 'K' for Predefined Kit")
    name: str = Field(..., min_length=2, max_length=255, description="Name of the bundle/kit")
    product_id: Optional[int] = Field(None, description="Optional 5-digit ECWID Product ID namespace")
    components: List[BundleComponentInput] = Field(..., min_length=1, description="List of components")
    target_price: Optional[float] = Field(None, description="Optional selling price")


class OrbitCreateVariantRequest(BaseModel):
    """Request to generate a new Color / Condition Variant (UPIS Layer 2)."""
    source_variant_id: int = Field(..., description="Existing variant ID to clone identity from")
    color_code: str = Field(..., min_length=1, max_length=2, description="BK, WY, SV, GY, BL, RD, BG, GD")
    condition_code: Optional[str] = Field("U", description="'N' New, 'R' Refurbished, 'U' Used")
    variant_name: Optional[str] = None


class OrbitUpdateRelationshipRequest(BaseModel):
    """Request to update a relationship tether."""
    target_type: str = Field(..., description="'listing' or 'component'")
    source_variant_id: int
    target_id: int
    relationship_type: RelationshipType


class OrbitUnlinkRequest(BaseModel):
    """Request to unlink a node or relationship tether."""
    target_type: str = Field(..., description="'listing' or 'component'")
    target_id: int
    source_variant_id: int


class OrbitConvertTypeRequest(BaseModel):
    """Request to convert an existing product variant to Kit (K), Bundle (B), or Base Product."""
    variant_id: int = Field(..., description="Target variant ID to convert")
    target_type: str = Field(..., description="'K' (Predefined Kit), 'B' (USAV Bundle), or 'Product' (Base)")
    components: Optional[List[BundleComponentInput]] = Field(default_factory=list, description="Optional initial components")


# ============================================================================
# AI DEEP CLASSIFICATION SCHEMAS
# ============================================================================

class AIDeepClassifyRequest(BaseModel):
    """Request for AI deep product classification."""
    variant_id: int = Field(..., ge=1)


class AIClassifiedComponent(BaseModel):
    """A component suggested by AI, optionally matched to existing catalog."""
    component_name: str
    suggested_quantity: int = 1
    suggested_role: str = "PRIMARY"
    matched_variant_id: Optional[int] = None
    matched_sku: Optional[str] = None
    matched_name: Optional[str] = None
    match_confidence: float = 0.0


class AIClassifiedParent(BaseModel):
    """A parent product this item may be a component of."""
    parent_name: str
    matched_variant_id: Optional[int] = None
    matched_sku: Optional[str] = None
    matched_name: Optional[str] = None
    match_confidence: float = 0.0


class AIDeepClassifyResponse(BaseModel):
    """Response from AI deep product classification."""
    variant_id: int
    full_sku: str
    current_type: str
    suggested_type: str = Field(..., description="'Product', 'K', 'B', 'P'")
    type_confidence: float = Field(..., ge=0.0, le=1.0)
    type_reasoning: str
    suggested_components: List[AIClassifiedComponent] = Field(default_factory=list)
    suggested_parents: List[AIClassifiedParent] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class BundleParticipation(BaseModel):
    """A bundle/kit that this product participates in."""
    parent_variant_id: int
    parent_sku: str
    parent_name: Optional[str] = None
    parent_type: str  # 'K' or 'B'
    role: str
    quantity_required: int = 1
    sibling_components: List[ProductNode] = Field(default_factory=list)


class BundleDiscoveryResponse(BaseModel):
    """All bundles/kits this product participates in."""
    variant_id: int
    full_sku: str
    participations: List[BundleParticipation] = Field(default_factory=list)
