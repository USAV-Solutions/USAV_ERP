/**
 * sync.ts – Force-sync API wrappers (two-way Zoho sync engine).
 *
 * All endpoints return 202 Accepted with { status, entity, id }.
 */
import axiosClient from './axiosClient'
import { SYNC } from './endpoints'

export interface ForceSyncResponse {
  status: 'queued'
  entity: 'item' | 'order' | 'customer'
  id: number
}

export async function forceSyncItem(variantId: number): Promise<ForceSyncResponse> {
  const { data } = await axiosClient.post<ForceSyncResponse>(SYNC.ITEM(variantId))
  return data
}

export async function forceSyncOrder(orderId: number): Promise<ForceSyncResponse> {
  const { data } = await axiosClient.post<ForceSyncResponse>(SYNC.ORDER(orderId))
  return data
}

export async function forceSyncCustomer(customerId: number): Promise<ForceSyncResponse> {
  const { data } = await axiosClient.post<ForceSyncResponse>(SYNC.CUSTOMER(customerId))
  return data
}
