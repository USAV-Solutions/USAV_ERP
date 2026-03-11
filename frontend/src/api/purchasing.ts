import axiosClient from './axiosClient'
import { PURCHASING } from './endpoints'
import type {
  PurchaseOrderItemCreate,
  PurchaseOrder,
  PurchaseOrderCreate,
  PurchaseOrderItem,
  PurchaseOrderItemMatchRequest,
  PurchaseOrderReceiveRequest,
  PurchaseOrderReceiveResponse,
  Vendor,
  VendorCreate,
  ZohoPurchaseImportResponse,
} from '../types/purchasing'

export async function listVendors(): Promise<Vendor[]> {
  const { data } = await axiosClient.get<Vendor[]>(PURCHASING.VENDORS)
  return data
}

export async function createVendor(body: VendorCreate): Promise<Vendor> {
  const { data } = await axiosClient.post<Vendor>(PURCHASING.VENDORS, body)
  return data
}

export async function updateVendor(vendorId: number, body: Partial<VendorCreate>): Promise<Vendor> {
  const { data } = await axiosClient.patch<Vendor>(PURCHASING.VENDOR(vendorId), body)
  return data
}

export async function listPurchaseOrders(): Promise<PurchaseOrder[]> {
  const { data } = await axiosClient.get<PurchaseOrder[]>(PURCHASING.PURCHASES)
  return data
}

export async function listPurchaseOrdersPaged(params: {
  skip?: number
  limit?: number
} = {}): Promise<PurchaseOrder[]> {
  const query = new URLSearchParams()
  if (params.skip !== undefined) query.set('skip', String(params.skip))
  if (params.limit !== undefined) query.set('limit', String(params.limit))

  const qs = query.toString()
  const url = qs ? `${PURCHASING.PURCHASES}?${qs}` : PURCHASING.PURCHASES
  const { data } = await axiosClient.get<PurchaseOrder[]>(url)
  return data
}

export async function getPurchaseOrder(poId: number): Promise<PurchaseOrder> {
  const { data } = await axiosClient.get<PurchaseOrder>(PURCHASING.PURCHASE(poId))
  return data
}

export async function createPurchaseOrder(body: PurchaseOrderCreate): Promise<PurchaseOrder> {
  const { data } = await axiosClient.post<PurchaseOrder>(PURCHASING.PURCHASES, body)
  return data
}

export async function addPurchaseOrderItem(
  poId: number,
  body: PurchaseOrderItemCreate,
): Promise<PurchaseOrderItem> {
  const { data } = await axiosClient.post<PurchaseOrderItem>(PURCHASING.PURCHASE_ITEMS(poId), body)
  return data
}

export async function matchPurchaseItem(
  itemId: number,
  body: PurchaseOrderItemMatchRequest,
): Promise<PurchaseOrderItem> {
  const { data } = await axiosClient.post<PurchaseOrderItem>(PURCHASING.MATCH_ITEM(itemId), body)
  return data
}

export async function markPurchaseDelivered(
  poId: number,
  body: PurchaseOrderReceiveRequest,
): Promise<PurchaseOrderReceiveResponse> {
  const { data } = await axiosClient.post<PurchaseOrderReceiveResponse>(
    PURCHASING.MARK_DELIVERED(poId),
    body,
  )
  return data
}

export async function importPurchasesFromZoho(): Promise<ZohoPurchaseImportResponse> {
  const { data } = await axiosClient.post<ZohoPurchaseImportResponse>(PURCHASING.IMPORT_ZOHO)
  return data
}
