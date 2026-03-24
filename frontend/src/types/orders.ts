/* ------------------------------------------------------------------ *
 *  TypeScript interfaces for the Orders module.                       *
 *  Mirrors Backend Pydantic schemas:                                  *
 *    - modules/orders/schemas/orders.py                               *
 *    - modules/orders/schemas/sync.py                                 *
 * ------------------------------------------------------------------ */

// ── Enums ────────────────────────────────────────────────────────────

export type OrderPlatform =
  | 'AMAZON'
  | 'EBAY_MEKONG'
  | 'EBAY_USAV'
  | 'EBAY_DRAGON'
  | 'ECWID'
  | 'ZOHO'
  | 'MANUAL'

export type OrderStatus =
  | 'PENDING'
  | 'PROCESSING'
  | 'READY_TO_SHIP'
  | 'SHIPPED'
  | 'DELIVERED'
  | 'CANCELLED'
  | 'REFUNDED'
  | 'ON_HOLD'
  | 'ERROR'

export type OrderItemStatus =
  | 'UNMATCHED'
  | 'MATCHED'
  | 'ALLOCATED'
  | 'SHIPPED'
  | 'CANCELLED'

export type ShippingStatus =
  | 'PENDING'
  | 'ON_HOLD'
  | 'CANCELLED'
  | 'PACKED'
  | 'SHIPPING'
  | 'DELIVERED'

export type IntegrationSyncStatus = 'IDLE' | 'SYNCING' | 'ERROR'
export type ZohoSyncStatus = 'PENDING' | 'SYNCED' | 'ERROR' | 'DIRTY'

// ── Order Item Schemas ───────────────────────────────────────────────

export interface OrderItemBrief {
  id: number
  external_item_id: string | null
  external_sku: string | null
  external_asin: string | null
  item_name: string
  quantity: number
  unit_price: string
  total_price: string
  status: OrderItemStatus
  variant_id: number | null
  variant_sku: string | null
  matching_notes: string | null
}

export interface OrderItemDetail extends OrderItemBrief {
  allocated_inventory_id: number | null
  item_metadata: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

export interface VariantSearchResult {
  id: number
  identity_id?: number
  identity_type?: 'Product' | 'P' | 'B' | 'K'
  generated_upis_h?: string
  full_sku: string
  variant_name?: string | null
  product_name: string
  color_code: string | null
  condition_code: string | null
}

export interface OrderItemMatchRequest {
  variant_id: number
  learn?: boolean
  notes?: string
}

export interface OrderItemConfirmRequest {
  notes?: string
}

// ── Order Header Schemas ─────────────────────────────────────────────

export interface OrderBrief {
  id: number
  platform: OrderPlatform
  external_order_id: string
  external_order_number: string | null
  status: OrderStatus
  shipping_status: ShippingStatus
  zoho_sync_status: ZohoSyncStatus
  customer_name: string | null
  total_amount: string
  currency: string
  ordered_at: string | null
  created_at: string
  item_count: number
  unmatched_count: number
}

export interface OrderDetail {
  id: number
  platform: OrderPlatform
  external_order_id: string
  external_order_number: string | null
  status: OrderStatus
  shipping_status: ShippingStatus
  zoho_sync_status: ZohoSyncStatus

  customer_name: string | null
  customer_email: string | null

  shipping_address_line1: string | null
  shipping_address_line2: string | null
  shipping_city: string | null
  shipping_state: string | null
  shipping_postal_code: string | null
  shipping_country: string | null

  subtotal_amount: string
  tax_amount: string
  shipping_amount: string
  total_amount: string
  currency: string

  ordered_at: string | null
  shipped_at: string | null
  tracking_number: string | null
  carrier: string | null

  processing_notes: string | null
  error_message: string | null

  items: OrderItemDetail[]

  created_at: string
  updated_at: string
}

export interface OrderListResponse {
  total: number
  skip: number
  limit: number
  items: OrderBrief[]
}

export interface OrderStatusUpdate {
  status: OrderStatus
  notes?: string
}

export interface ShippingStatusUpdate {
  shipping_status: ShippingStatus
  tracking_number?: string
  carrier?: string
  notes?: string
}

// ── Sync Schemas ─────────────────────────────────────────────────────

export interface IntegrationStateResponse {
  id: number
  platform_name: string
  last_successful_sync: string | null
  current_status: IntegrationSyncStatus
  last_error_message: string | null
  updated_at: string
}

export interface SyncRequest {
  platform?: string
}

export interface SyncRangeRequest {
  platform?: string
  since: string
  until: string
}

export interface SyncResponse {
  platform: string
  new_orders: number
  new_items: number
  auto_matched: number
  skipped_duplicates: number
  errors: string[]
  success: boolean
}

export interface SyncStatusResponse {
  platforms: IntegrationStateResponse[]
  total_orders: number
  total_unmatched_items: number
  total_matched_items: number
}
