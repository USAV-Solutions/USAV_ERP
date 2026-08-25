export type ZohoSyncStatus = 'SYNCED' | 'PENDING' | 'ERROR' | 'DIRTY'
export type ProductType = 'Product' | 'P' | 'B' | 'K'
export type ItemCondition = 'NEW' | 'REFURBISHED' | 'USED'
export type ItemStatus = 'IN_STOCK' | 'SOLD' | 'RESERVED' | 'DAMAGED'

// Lookup Types
export interface Brand {
  id: number
  name: string
  created_at: string
  updated_at: string
}

export interface Color {
  id: number
  name: string
  code: string
  created_at: string
  updated_at: string
}

export interface Condition {
  id: number
  name: string
  code: string
  created_at: string
  updated_at: string
}

export interface LCIDefinition {
  id: number
  product_id: number
  lci_index: number
  component_name: string
  created_at: string
  updated_at: string
}

// Product Types
export interface ProductFamily {
  product_id: number
  base_name: string
  description?: string
  brand_id?: number
  brand?: Brand
  kit_included_products?: string
  created_at: string
  updated_at: string
}

export interface ProductIdentity {
  id: number
  product_id: number
  type: ProductType
  is_stationery: boolean
  lci?: number
  identity_name?: string
  dimension_length?: number
  dimension_width?: number
  dimension_height?: number
  weight?: number
  generated_upis_h: string
  hex_signature: string
  physical_class?: string
  created_at: string
  updated_at: string
  family?: ProductFamily
}

export interface IdentitySearchResult {
  id: number
  product_id: number
  type: ProductType
  is_stationery?: boolean
  lci?: number | null
  generated_upis_h: string
  identity_name?: string | null
  family_name: string
}

export interface FamilySearchResult {
  product_id: number
  family_code: string
  base_name: string
}

export interface Variant {
  id: number
  identity_id: number
  full_sku: string
  variant_name?: string
  thumbnail_url?: string | null
  color_code?: string
  condition_code?: string
  zoho_sync_status: ZohoSyncStatus
  zoho_item_id?: string
  zoho_error?: string
  is_active: boolean
  created_at: string
  updated_at: string
  identity?: ProductIdentity
}

export interface InventoryItem {
  id: number
  serial_number: string
  variant_id: number
  location_code: string
  status: ItemStatus
  cost_basis?: number
  received_at: string
  updated_at: string
}

export interface InventoryAudit {
  sku: string
  items: InventoryItem[]
  total_count: number
}

// Extended types for the inventory management page
export interface InventoryListItem {
  id: number
  full_sku: string
  name: string
  type: ProductType
  color_code?: string
  condition_code?: string
  parent_upis_h: string
  brand?: string
  zoho_sync_status: ZohoSyncStatus
  is_active: boolean
}

export interface GroupedInventoryItem {
  parent_upis_h: string
  name: string
  type: ProductType
  brand?: string
  alias_count: number
  variants: InventoryListItem[]
}

// Create product form types
export interface CreateProductFormData {
  type: ProductType
  name: string
  dimension_length?: number
  dimension_width?: number
  dimension_height?: number
  weight?: number
  brand_id?: number
  color_id?: number
  condition_id?: number
  // Bundle-specific
  component_skus?: string[]
  // Kit-specific
  included_products?: string
  // Part-specific
  parent_product_id?: number
  lci_id?: number
}

// Bundle component
export interface BundleComponent {
  parent_identity_id: number
  child_identity_id: number
  quantity_required: number
  role: 'Primary' | 'Accessory' | 'Satellite'
}

// Platform types
export type Platform = 'AMAZON' | 'EBAY_MEKONG' | 'EBAY_USAV' | 'EBAY_DRAGON' | 'EBAY_PURCHASING' | 'ECWID' | 'SHOPIFY' | 'WALMART'
export type PlatformSyncStatus = 'PENDING' | 'SYNCED' | 'ERROR'

export interface PlatformListing {
  id: number
  variant_id: number | null
  platform: Platform
  external_ref_id?: string
  merchant_sku?: string
  listed_name?: string
  listed_description?: string
  listing_price?: number
  listing_quantity?: number
  listing_type?: string
  listing_condition?: string
  upc?: string
  sync_status: PlatformSyncStatus
  last_synced_at?: string
  sync_error_message?: string
  created_at: string
  updated_at: string
  variant?: Variant
}

export interface PlatformListingCreate {
  variant_id: number
  platform: Platform
  external_ref_id?: string
  merchant_sku?: string
  listed_name?: string
  listed_description?: string
  listing_price?: number
  listing_quantity?: number
  listing_type?: string
  listing_condition?: string
  upc?: string
}

export interface PlatformListingUpdate {
  external_ref_id?: string
  merchant_sku?: string
  listed_name?: string
  listed_description?: string
  listing_price?: number
  listing_quantity?: number
  listing_type?: string
  listing_condition?: string
  upc?: string
}

export type RelationshipType =
  | 'EXACT'
  | 'ACCESSORY'
  | 'BUNDLE_COMPONENT'
  | 'KIT_COMPONENT'
  | 'PART_LCI'
  | 'SIBLING_VARIANT'
  | 'BUNDLE'
  | 'PART'
  | 'RELATED_PRODUCT'

export type StockWarningStatus = 'HEALTHY' | 'LOW_STOCK' | 'OUT_OF_STOCK'

export interface PriceMismatchAlert {
  has_mismatch: boolean
  ecwid_price?: number | null
  shopify_price?: number | null
  price_diff?: number | null
  message?: string | null
}

export interface ChannelSalesMetric {
  platform: string
  units_sold_30d: number
  revenue_30d: number
  units_sold_90d: number
  revenue_90d: number
}

export interface OrbitAnalyticsResponse {
  variant_id: number
  full_sku: string
  units_sold_30d: number
  revenue_30d: number
  units_sold_90d: number
  revenue_90d: number
  monthly_velocity: number
  available_stock: number
  runway_days?: number | null
  stock_warning: StockWarningStatus
  price_mismatch: PriceMismatchAlert
  channel_metrics: ChannelSalesMetric[]
}

export interface BundleComponentInput {
  child_variant_id: number
  quantity_required: number
  role: string
}

export interface OrbitCreateBundleKitRequest {
  type: 'B' | 'K'
  name: string
  product_id?: number | null
  components: BundleComponentInput[]
  target_price?: number | null
}

export interface OrbitCreateVariantRequest {
  source_variant_id: number
  color_code: string
  condition_code?: string | null
  variant_name?: string | null
}

export interface OrbitUpdateRelationshipRequest {
  target_type: 'listing' | 'component'
  source_variant_id: number
  target_id: number
  relationship_type: RelationshipType
}

export interface OrbitUnlinkRequest {
  target_type: 'listing' | 'component'
  target_id: number
  source_variant_id: number
}

export interface ProductNode {
  variant_id: number
  full_sku: string
  variant_name?: string | null
  thumbnail_url?: string | null
  identity_name?: string | null
  family_name?: string | null
  family_code?: string | null
  condition_code?: string | null
  color_code?: string | null
  identity_type?: string | null
}

export interface ListingNode {
  listing_id: number
  variant_id?: number | null
  platform: Platform
  external_ref_id?: string | null
  merchant_sku?: string | null
  listed_name?: string | null
  listing_price?: number | null
  listing_quantity?: number | null
  sync_status: PlatformSyncStatus
  relationship_type?: RelationshipType
  last_synced_at?: string | null
  sync_error_message?: string | null
}

export interface GraphEdge {
  source: string
  target: string
  relationship: string
  relationship_type?: RelationshipType
  confidence?: number | null
}

export interface GraphTopologyResponse {
  product: ProductNode
  listings: ListingNode[]
  related_products?: ProductNode[]
  edges: GraphEdge[]
}

export interface AISuggestRequest {
  variant_id: number
  platforms?: Platform[]
  limit?: number
  include_linked?: boolean
}

export interface AISuggestion {
  listing_id: number
  platform: Platform
  external_ref_id?: string | null
  merchant_sku?: string | null
  listed_name?: string | null
  listing_price?: number | null
  relationship_type?: RelationshipType
  confidence: number
  reasons: string[]
}

export interface AISuggestResponse {
  variant_id: number
  variant_sku: string
  variant_name?: string | null
  suggestions: AISuggestion[]
}

export interface LockRelationshipRequest {
  listing_id: number
  variant_id: number
  relationship_type?: RelationshipType
  enrich_metadata?: boolean
}

export interface LockRelationshipResponse {
  success: boolean
  listing_id: number
  variant_id: number
  platform: Platform
  relationship_type?: RelationshipType
  enriched_fields: string[]
  message: string
}

export interface CompareRequest {
  listing_ids: number[]
}

export interface CompareField {
  key: string
  label: string
  values: Record<string, any>
}

export interface CompareResponse {
  listing_ids: number[]
  listings: ListingNode[]
  comparison_fields: CompareField[]
}


