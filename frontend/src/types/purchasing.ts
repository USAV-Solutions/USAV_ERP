export type PurchaseDeliverStatus = 'CREATED' | 'BILLED' | 'DELIVERED'
export type PurchaseOrderItemStatus = 'UNMATCHED' | 'MATCHED' | 'RECEIVED'

export interface Vendor {
  id: number
  name: string
  email?: string | null
  phone?: string | null
  address?: string | null
  is_active: boolean
  zoho_id?: string | null
  created_at: string
  updated_at: string
}

export interface VendorCreate {
  name: string
  email?: string
  phone?: string
  address?: string
  is_active?: boolean
}

export interface PurchaseOrderItem {
  id: number
  purchase_order_id: number
  variant_id?: number | null
  variant_sku?: string | null
  external_item_id?: string | null
  external_item_name: string
  quantity: number
  unit_price: number
  total_price: number
  status: PurchaseOrderItemStatus
  created_at: string
  updated_at: string
}

export interface PurchaseOrderItemCreate {
  variant_id?: number
  external_item_id?: string
  external_item_name: string
  quantity: number
  unit_price: number
  total_price: number
  status?: PurchaseOrderItemStatus
}

export interface PurchaseOrder {
  id: number
  po_number: string
  vendor_id: number
  deliver_status: PurchaseDeliverStatus
  order_date: string
  expected_delivery_date?: string | null
  total_amount: number
  currency: string
  tracking_number?: string | null
  tax_amount?: number
  shipping_amount?: number
  handling_amount?: number
  source?: string
  notes?: string | null
  zoho_id?: string | null
  vendor?: Vendor
  items: PurchaseOrderItem[]
  created_at: string
  updated_at: string
}

export interface PurchaseOrderCreate {
  po_number: string
  vendor_id: number
  deliver_status?: PurchaseDeliverStatus
  order_date: string
  expected_delivery_date?: string
  total_amount: number
  currency?: string
  tracking_number?: string
  tax_amount?: number
  shipping_amount?: number
  handling_amount?: number
  source?: string
  notes?: string
  items?: PurchaseOrderItemCreate[]
}

export interface PurchaseOrderItemMatchRequest {
  variant_id: number
}

export interface PurchaseOrderItemUpdate {
  variant_id?: number | null
  external_item_id?: string | null
  external_item_name?: string
  quantity?: number
  unit_price?: number
  total_price?: number
  status?: PurchaseOrderItemStatus
}

export interface ItemReceipt {
  purchase_order_item_id: number
  quantity_received: number
  serial_numbers: string[]
  location_code?: string
}

export interface PurchaseOrderReceiveRequest {
  items: ItemReceipt[]
}

export interface PurchaseOrderReceiveResponse {
  purchase_order_id: number
  created_inventory_item_ids: number[]
  deliver_status: PurchaseDeliverStatus
}

export interface ZohoPurchaseImportResponse {
  vendors_created: number
  vendors_updated: number
  purchase_orders_created: number
  purchase_orders_updated: number
  purchase_order_items_replaced: number
  source_vendors_seen: number
  source_purchase_orders_seen: number
}

export interface GoodwillCsvImportResponse {
  purchase_orders_created: number
  purchase_orders_updated: number
  purchase_order_items_created: number
  purchase_order_items_updated: number
  source_rows_seen: number
  source_rows_skipped: number
}
