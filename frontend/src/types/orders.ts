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
  | 'CANCELLED'
  | 'ERROR'

export type OrderItemStatus =
  | 'UNMATCHED'
  | 'MATCHED'
  | 'ALLOCATED'
  | 'SHIPPED'
  | 'CANCELLED'

export interface OrderItem {
  id: number
  order_id: number
  item_name: string
  quantity: number
  unit_price: string
  total_price: string
  external_item_id?: string
  external_sku?: string
  external_asin?: string
  variant_id?: number
  allocated_inventory_id?: number
  status: OrderItemStatus
  matching_notes?: string
  item_metadata?: Record<string, any>
  created_at: string
  updated_at: string
}

export interface Order {
  id: number
  platform: OrderPlatform
  external_order_id: string
  external_order_number?: string
  customer_name?: string
  customer_email?: string
  ship_address_line1?: string
  ship_address_line2?: string
  ship_city?: string
  ship_state?: string
  ship_postal_code?: string
  ship_country?: string
  subtotal_amount: string
  tax_amount: string
  shipping_amount: string
  total_amount: string
  currency: string
  status: OrderStatus
  ordered_at?: string
  shipped_at?: string
  tracking_number?: string
  carrier?: string
  processing_notes?: string
  order_metadata?: Record<string, any>
  created_at: string
  updated_at: string
  items?: OrderItem[]
}

export interface OrderSummary {
  total_orders: number
  pending_orders: number
  processing_orders: number
  ready_to_ship_orders: number
  shipped_orders: number
  orders_with_errors: number
  total_revenue: string
  unmatched_items: number
}

export interface SyncResult {
  success: boolean
  platform: string
  date: string
  total_fetched: number
  new_orders: number
  existing_orders: number
  errors: number
  error_message?: string
}
