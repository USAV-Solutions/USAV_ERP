export type ReturnPlatform =
  | 'AMAZON'
  | 'EBAY_MEKONG'
  | 'EBAY_USAV'
  | 'EBAY_DRAGON'
  | 'ECWID'
  | 'SHOPIFY'
  | 'WALMART'
  | 'ZOHO'
  | 'MANUAL'

export type ReturnNormalizedStatus =
  | 'RETURNED'
  | 'PARTIALLY_RETURNED'
  | 'REFUNDED'
  | 'PARTIALLY_REFUNDED'
  | 'CANCELLED'
  | 'PARTIALLY_CANCELLED'
  | 'UNKNOWN'

export type ReturnIntegrationSyncStatus = 'IDLE' | 'SYNCING' | 'ERROR'

export type ReturnZohoSyncStatus =
  | 'PENDING'
  | 'READY_TO_SYNC'
  | 'MISSING_LOCAL_ORDER'
  | 'MISSING_ZOHO_ORDER'
  | 'MISSING_LINE_ITEM_MAPPING'
  | 'QUANTITY_CONFLICT'
  | 'ALREADY_SYNCED'
  | 'SYNCED'
  | 'ERROR'

export interface ReturnItemDetail {
  id: number
  linked_order_item_id: number | null
  external_item_id: string | null
  external_sku: string | null
  item_name: string
  ordered_qty: number
  returned_qty: number
  cancelled_qty: number
  refunded_amount: string
  item_payload: Record<string, unknown> | null
}

export interface ReturnRecordBrief {
  id: number
  platform: ReturnPlatform
  source: string
  external_record_key: string
  external_order_id: string
  external_return_id: string | null
  linked_order_id: number | null
  customer_name: string | null
  customer_email: string | null
  ordered_at: string | null
  event_at: string | null
  last_source_updated_at: string | null
  normalized_status: ReturnNormalizedStatus
  source_status: string | null
  source_substatus: string | null
  reason: string | null
  order_total_amount: string
  refunded_amount: string
  currency: string
  item_count: number
  returned_qty_total: number
  cancelled_qty_total: number
  zoho_salesreturn_id: string | null
  zoho_salesreturn_number: string | null
  zoho_sync_status: ReturnZohoSyncStatus
  zoho_sync_error: string | null
  zoho_synced_at: string | null
  created_at: string
  updated_at: string
}

export interface ReturnRecordDetail extends ReturnRecordBrief {
  raw_payload: Record<string, unknown> | null
  items: ReturnItemDetail[]
}

export interface ReturnListResponse {
  total: number
  skip: number
  limit: number
  items: ReturnRecordBrief[]
  summary_counts: Record<string, number>
}

export interface ReturnSyncStateResponse {
  id: number
  platform_name: string
  last_successful_sync: string | null
  current_status: ReturnIntegrationSyncStatus
  last_error_message: string | null
  updated_at: string
}

export interface ReturnSyncStatusResponse {
  platforms: ReturnSyncStateResponse[]
  total_records: number
  counts_by_status: Record<string, number>
}

export interface ReturnSyncRequest {
  platform?: string
}

export interface ReturnSyncRangeRequest {
  platform?: string
  since: string
  until: string
}

export interface ReturnSyncResponse {
  platform: string
  new_records: number
  updated_records: number
  new_items: number
  linked_orders: number
  linked_items: number
  skipped_duplicates: number
  errors: string[]
  success: boolean
}

export interface ReturnZohoLineValidationResponse {
  return_item_id: number
  linked_order_item_id: number | null
  quantity: number
  zoho_item_id: string | null
  zoho_salesorder_item_id: string | null
  status: ReturnZohoSyncStatus
  message: string | null
}

export interface ReturnZohoValidationResponse {
  record_id: number
  status: ReturnZohoSyncStatus
  blockers: string[]
  zoho_salesorder_id: string | null
  zoho_salesreturn_id: string | null
  zoho_salesreturn_number: string | null
  line_items: ReturnZohoLineValidationResponse[]
}
