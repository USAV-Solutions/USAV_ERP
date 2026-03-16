/**
 * Orders API service layer.
 *
 * Thin wrappers around axiosClient that call the backend order endpoints
 * and return strongly-typed responses.
 */
import axiosClient from './axiosClient'
import { ORDERS, CATALOG } from './endpoints'
import type {
  OrderDetail,
  OrderListResponse,
  OrderStatusUpdate,
  ShippingStatusUpdate,
  OrderItemDetail,
  OrderItemMatchRequest,
  OrderItemConfirmRequest,
  SyncRequest,
  SyncRangeRequest,
  SyncResponse,
  SyncStatusResponse,
  IntegrationStateResponse,
  OrderPlatform,
  OrderStatus,
  OrderItemStatus,
  VariantSearchResult,
} from '../types/orders'

// ── Order CRUD ───────────────────────────────────────────────────────

export interface ListOrdersParams {
  skip?: number
  limit?: number
  platform?: OrderPlatform
  status?: OrderStatus
  item_status?: OrderItemStatus
  search?: string
}

export async function listOrders(params: ListOrdersParams = {}): Promise<OrderListResponse> {
  const query = new URLSearchParams()
  if (params.skip !== undefined) query.set('skip', String(params.skip))
  if (params.limit !== undefined) query.set('limit', String(params.limit))
  if (params.platform) query.set('platform', params.platform)
  if (params.status) query.set('status', params.status)
  if (params.item_status) query.set('item_status', params.item_status)
  if (params.search) query.set('search', params.search)

  const qs = query.toString()
  const url = qs ? `${ORDERS.LIST}?${qs}` : ORDERS.LIST
  const { data } = await axiosClient.get<OrderListResponse>(url)
  return data
}

export async function getOrder(orderId: number): Promise<OrderDetail> {
  const { data } = await axiosClient.get<OrderDetail>(ORDERS.ORDER(orderId))
  return data
}

export async function updateOrderStatus(
  orderId: number,
  body: OrderStatusUpdate,
): Promise<OrderDetail> {
  const { data } = await axiosClient.patch<OrderDetail>(ORDERS.UPDATE_STATUS(orderId), body)
  return data
}

export async function updateShippingStatus(
  orderId: number,
  body: ShippingStatusUpdate,
): Promise<OrderDetail> {
  const { data } = await axiosClient.patch<OrderDetail>(ORDERS.UPDATE_SHIPPING(orderId), body)
  return data
}

export async function deleteOrder(orderId: number): Promise<void> {
  await axiosClient.delete(ORDERS.DELETE(orderId))
}

// ── Sync ─────────────────────────────────────────────────────────────

export async function syncOrders(body: SyncRequest = {}): Promise<SyncResponse[]> {
  const { data } = await axiosClient.post<SyncResponse[]>(ORDERS.SYNC, body)
  return data
}

export async function syncOrdersRange(body: SyncRangeRequest): Promise<SyncResponse[]> {
  const { data } = await axiosClient.post<SyncResponse[]>(ORDERS.SYNC_RANGE, body)
  return data
}

export async function getSyncStatus(): Promise<SyncStatusResponse> {
  const { data } = await axiosClient.get<SyncStatusResponse>(ORDERS.SYNC_STATUS)
  return data
}

export async function resetSyncState(platform: string): Promise<IntegrationStateResponse> {
  const { data } = await axiosClient.post<IntegrationStateResponse>(ORDERS.SYNC_RESET(platform))
  return data
}

// ── SKU Resolution ───────────────────────────────────────────────────

export async function matchItem(
  itemId: number,
  body: OrderItemMatchRequest,
): Promise<OrderItemDetail> {
  const { data } = await axiosClient.post<OrderItemDetail>(ORDERS.MATCH_ITEM(itemId), body)
  return data
}

export async function confirmItem(
  itemId: number,
  body: OrderItemConfirmRequest = {},
): Promise<OrderItemDetail> {
  const { data } = await axiosClient.post<OrderItemDetail>(ORDERS.CONFIRM_ITEM(itemId), body)
  return data
}

export async function rejectItem(itemId: number): Promise<OrderItemDetail> {
  const { data } = await axiosClient.post<OrderItemDetail>(ORDERS.REJECT_ITEM(itemId))
  return data
}

// ── Variant Search (for SKU resolution) ──────────────────────────────

export async function searchVariants(query: string, limit = 20): Promise<VariantSearchResult[]> {
  const { data } = await axiosClient.get<VariantSearchResult[]>(CATALOG.VARIANT_SEARCH, {
    params: { q: query, limit },
  })
  return data
}
