import axiosClient from './axiosClient'
import { PURCHASING } from './endpoints'
import type {
  GoodwillCsvImportResponse,
  PurchaseOrderItemCreate,
  PurchaseOrder,
  PurchaseOrderCreate,
  PurchaseOrderItem,
  PurchaseOrderItemMatchRequest,
  PurchaseOrderItemUpdate,
  PurchaseOrderReceiveRequest,
  PurchaseOrderReceiveResponse,
  Vendor,
  VendorCreate,
  ZohoPurchaseImportResponse,
  ZohoSinglePurchaseImportResponse,
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

export async function updatePurchaseItem(
  itemId: number,
  body: PurchaseOrderItemUpdate,
): Promise<PurchaseOrderItem> {
  const { data } = await axiosClient.patch<PurchaseOrderItem>(PURCHASING.PURCHASE_ITEM(itemId), body)
  return data
}

export async function deletePurchaseItem(itemId: number): Promise<void> {
  await axiosClient.delete(PURCHASING.PURCHASE_ITEM(itemId))
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

export async function importOneRandomPurchaseFromZoho(params?: {
  sourcePage?: number
  perPage?: number
}): Promise<ZohoSinglePurchaseImportResponse> {
  const query = new URLSearchParams()
  if (params?.sourcePage !== undefined) query.set('source_page', String(params.sourcePage))
  if (params?.perPage !== undefined) query.set('per_page', String(params.perPage))

  const qs = query.toString()
  const url = qs
    ? `${PURCHASING.IMPORT_ZOHO_RANDOM_ONE}?${qs}`
    : PURCHASING.IMPORT_ZOHO_RANDOM_ONE

  const { data } = await axiosClient.post<ZohoSinglePurchaseImportResponse>(url)
  return data
}

export async function importPurchasesFromGoodwillCsv(file: File): Promise<GoodwillCsvImportResponse> {
  const formData = new FormData()
  formData.append('file', file)
  const { data } = await axiosClient.post<GoodwillCsvImportResponse>(
    PURCHASING.IMPORT_GOODWILL_CSV,
    formData,
    {
      headers: { 'Content-Type': 'multipart/form-data' },
    },
  )
  return data
}
