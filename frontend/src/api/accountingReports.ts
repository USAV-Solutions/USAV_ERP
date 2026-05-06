import axiosClient from './axiosClient'
import { ACCOUNTING } from './endpoints'

export type GroupBy = 'sku' | 'week' | 'month' | 'quarter' | 'year' | 'source' | 'vendor'

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

export async function fetchPurchaseOrderReport(params: {
  startDate: string
  endDate: string
  groupBy: GroupBy
}): Promise<PurchaseOrderReportRow[]> {
  const query = new URLSearchParams()
  query.set('start_date', params.startDate)
  query.set('end_date', params.endDate)
  query.set('group_by', params.groupBy)

  const { data } = await axiosClient.get<{ rows: PurchaseOrderReportRow[] }>(
    `${ACCOUNTING.PURCHASE_ORDER_REPORTS}?${query.toString()}`,
  )
  return data.rows ?? []
}

export async function exportPurchaseOrderReport(params: {
  startDate: string
  endDate: string
  groupBy: GroupBy
  fileType: 'csv' | 'xlsx'
}): Promise<Blob> {
  const query = new URLSearchParams()
  query.set('start_date', params.startDate)
  query.set('end_date', params.endDate)
  query.set('group_by', params.groupBy)
  query.set('file_type', params.fileType)

  const { data } = await axiosClient.get(
    `${ACCOUNTING.PURCHASE_ORDER_REPORTS_EXPORT}?${query.toString()}`,
    { responseType: 'blob' },
  )
  return data as Blob
}
