"""
Graph and AI Matching Schemas for Listing Management.
"""
import enum
from datetime import datetime
from typing import Any, Optional, List, Dict
from pydantic import BaseModel, ConfigDict, Field

from app.models import Platform, PlatformSyncStatus


class RelationshipType(str, enum.Enum):
    """Semantic relationship types between catalog entities and listings."""
    EXACT = "EXACT"                  # Direct 1:1 listing of physical product
    BUNDLE = "BUNDLE"                # Multi-item bundle containing this product
    ACCESSORY = "ACCESSORY"          # Compatible accessory (e.g. bluetooth adapter, bracket, cable)
    PART = "PART"                    # Sub-assembly or replacement part
    RELATED_PRODUCT = "RELATED_PRODUCT"  # Related variant or family sibling


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


class GraphTopologyResponse(BaseModel):
    """Full graph topology for visualizer canvas."""
    product: ProductNode
    listings: List[ListingNode] = Field(default_factory=list)
    related_products: List[ProductNode] = Field(default_factory=list)
    edges: List[GraphEdge] = Field(default_factory=list)


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
    values: Dict[str, Any]  # mapping stringified listing_id -> value


class CompareResponse(BaseModel):
    """Side-by-side comparison response."""
    listing_ids: List[int]
    listings: List[ListingNode]
    comparison_fields: List[CompareField]
