/**
 * sync.ts – Force-sync API wrappers (two-way Zoho sync engine).
 *
 * All endpoints return 202 Accepted with { status, entity, id }.
 */
import axiosClient from './axiosClient'
import { SYNC } from './endpoints'

export interface ForceSyncResponse {
  status: 'queued'
  entity: 'item' | 'order' | 'purchase' | 'customer'
  id: number
}

export interface ForceSyncPurchasePeriodResponse {
  status: 'queued'
  entity: 'purchase'
  count: number
  ids: number[]
}

export async function forceSyncItem(variantId: number): Promise<ForceSyncResponse> {
  const { data } = await axiosClient.post<ForceSyncResponse>(SYNC.ITEM(variantId))
  return data
}

export async function forceSyncOrder(orderId: number): Promise<ForceSyncResponse> {
  const { data } = await axiosClient.post<ForceSyncResponse>(SYNC.ORDER(orderId))
  return data
}

export async function forceSyncPurchase(poId: number): Promise<ForceSyncResponse> {
  const { data } = await axiosClient.post<ForceSyncResponse>(SYNC.PURCHASE(poId))
  return data
}

export async function forceSyncPurchasesByPeriod(params: {
  orderDateFrom?: string
  orderDateTo?: string
  limit?: number
}): Promise<ForceSyncPurchasePeriodResponse> {
  const query = new URLSearchParams()
  if (params.orderDateFrom) {
    query.set('order_date_from', params.orderDateFrom)
  }
  if (params.orderDateTo) {
    query.set('order_date_to', params.orderDateTo)
  }
  if (typeof params.limit === 'number') {
    query.set('limit', String(params.limit))
  }

  const queryString = query.toString()
  const url = queryString ? `${SYNC.PURCHASES}?${queryString}` : SYNC.PURCHASES
  const { data } = await axiosClient.post<ForceSyncPurchasePeriodResponse>(url)
  return data
}

export async function forceSyncCustomer(customerId: number): Promise<ForceSyncResponse> {
  const { data } = await axiosClient.post<ForceSyncResponse>(SYNC.CUSTOMER(customerId))
  return data
}
