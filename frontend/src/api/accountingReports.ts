import axiosClient from './axiosClient'
import { ACCOUNTING } from './endpoints'

export type GroupBy = 'sku' | 'week' | 'month' | 'quarter' | 'year' | 'source' | 'vendor'
export type OrderBy = 'total_price' | 'sku' | 'source' | 'date'

export interface PurchaseOrderReportRow {
  group: string
  order_date: string
  order_number: string
  item: string
  sku: string
  source: string
  quantity: number
  total_price: string
  tax: string
  shipping: string
  handling: string
  vendor: string
}

export interface PurchaseOrderReportFilterOptions {
  item_options: { value: string; label: string }[]
  source_options: string[]
  vendor_options: string[]
}

function appendListParams(query: URLSearchParams, key: string, values?: string[]): void {
  for (const value of values ?? []) {
    if (value.trim()) {
      query.append(key, value.trim())
    }
  }
}

export async function fetchPurchaseOrderReport(params: {
  startDate: string
  endDate: string
  groupBy: GroupBy
  orderBy: OrderBy
  item?: string[]
  source?: string[]
  vendor?: string[]
}): Promise<PurchaseOrderReportRow[]> {
  const query = new URLSearchParams()
  query.set('start_date', params.startDate)
  query.set('end_date', params.endDate)
  query.set('group_by', params.groupBy)
  query.set('order_by', params.orderBy)
  appendListParams(query, 'item', params.item)
  appendListParams(query, 'source', params.source)
  appendListParams(query, 'vendor', params.vendor)

  const { data } = await axiosClient.get<{ rows: PurchaseOrderReportRow[] }>(
    `${ACCOUNTING.PURCHASE_ORDER_REPORTS}?${query.toString()}`,
  )
  return data.rows ?? []
}

export async function exportPurchaseOrderReport(params: {
  startDate: string
  endDate: string
  groupBy: GroupBy
  orderBy: OrderBy
  item?: string[]
  source?: string[]
  vendor?: string[]
  fileType: 'csv' | 'xlsx'
}): Promise<Blob> {
  const query = new URLSearchParams()
  query.set('start_date', params.startDate)
  query.set('end_date', params.endDate)
  query.set('group_by', params.groupBy)
  query.set('order_by', params.orderBy)
  appendListParams(query, 'item', params.item)
  appendListParams(query, 'source', params.source)
  appendListParams(query, 'vendor', params.vendor)
  query.set('file_type', params.fileType)

  const { data } = await axiosClient.get(
    `${ACCOUNTING.PURCHASE_ORDER_REPORTS_EXPORT}?${query.toString()}`,
    { responseType: 'blob' },
  )
  return data as Blob
}

export async function fetchPurchaseOrderReportFilterOptions(params: {
  startDate: string
  endDate: string
}): Promise<PurchaseOrderReportFilterOptions> {
  const query = new URLSearchParams()
  query.set('start_date', params.startDate)
  query.set('end_date', params.endDate)
  const { data } = await axiosClient.get<PurchaseOrderReportFilterOptions>(
    `${ACCOUNTING.PURCHASE_ORDER_REPORT_FILTER_OPTIONS}?${query.toString()}`,
  )
  return data
}
