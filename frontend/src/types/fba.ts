/**
 * Types for the server-side FBA order import.
 * Mirrors app/modules/fba/schemas.py.
 */

export type FbaImportStatus =
  | 'idle'
  | 'running'
  | 'completed'
  | 'completed_with_warnings'
  | 'aborted'
  | 'failed'

export type FbaImportPhase = 'parsing' | 'scraping' | 'ingesting' | 'done'

export type BuyerNameResult =
  | 'FOUND'
  | 'NOT_FOUND'
  | 'ERROR'
  | 'SKIPPED'
  | 'AUTH_EXPIRED'

export interface BuyerNameItem {
  order_id: string
  result: BuyerNameResult | null
  buyer_name: string | null
  detail: string | null
  attempts: number
  checked_at: string | null
}

export interface FbaImportJob {
  job_id: string | null
  status: FbaImportStatus
  phase: FbaImportPhase | null
  started_at: string | null
  finished_at: string | null
  all_order_rows: number
  fba_order_rows: number
  shipment_rows: number
  merged_rows: number
  total_names: number
  scraped_names: number
  counts: Record<string, number>
  orders_created: number
  orders_updated: number
  items_created: number
  warnings: string[]
  message: string | null
  last_error: string | null
  cancel_requested: boolean
  items: BuyerNameItem[]
}

export interface FbaReportHint {
  name: string
  url: string
  button: string
  file_format: string
  save_as: 'all_orders_txt' | 'fulfillment_csv'
}

export interface FbaPeriodHint {
  last_import_date: string | null
  days_needed: number
  option_days: number
  option_label: string
  reports: FbaReportHint[]
}

export type FbaAuthState = 'logged_in' | 'signed_out' | 'unverified'

export interface FbaAuthCheck {
  state: FbaAuthState
  detail: string | null
}

export const FBA_IMPORT_ACTIVE: FbaImportStatus[] = ['running']

export function isFbaImportActive(job?: FbaImportJob | null): boolean {
  return !!job && FBA_IMPORT_ACTIVE.includes(job.status)
}
