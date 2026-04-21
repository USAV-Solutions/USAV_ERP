import axiosClient from './axiosClient'
import { PURCHASING } from './endpoints'
import type {
  GoodwillCsvImportResponse,
  PurchaseFileImportResponse,
  PurchaseFileImportSource,
  PurchaseOrderItemCreate,
  PurchaseOrder,
  PurchaseOrderCreate,
  PurchaseOrderUpdate,
  PurchaseOrderItem,
  PurchaseOrderItemMatchRequest,
  PurchaseOrderItemUpdate,
  PurchaseOrderReceiveRequest,
  PurchaseOrderReceiveResponse,
  Vendor,
  VendorCreate,
  ZohoPurchaseImportResponse,
} from '../types/purchasing'

export async function listVendors(): Promise<Vendor[]> {
  const pageSize = 500
  const vendors: Vendor[] = []
  let skip = 0

  while (true) {
    const { data } = await axiosClient.get<Vendor[]>(
      `${PURCHASING.VENDORS}?skip=${skip}&limit=${pageSize}`,
    )
    vendors.push(...data)

    if (data.length < pageSize) {
      break
    }

    skip += data.length
  }

  return vendors
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
  poNumber?: string
  deliverStatus?: 'CREATED' | 'BILLED' | 'DELIVERED'
  itemMatchStatus?: 'matched' | 'unmatched'
  zohoSyncStatus?: 'PENDING' | 'SYNCED' | 'ERROR' | 'DIRTY'
  source?: string
  sortBy?: 'order_date' | 'po_number' | 'total_amount' | 'created_at'
  sortDir?: 'asc' | 'desc'
  orderDateFrom?: string
  orderDateTo?: string
} = {}): Promise<PurchaseOrder[]> {
  const query = new URLSearchParams()
  if (params.skip !== undefined) query.set('skip', String(params.skip))
  if (params.limit !== undefined) query.set('limit', String(params.limit))
  if (params.poNumber) query.set('po_number', params.poNumber)
  if (params.deliverStatus) query.set('deliver_status', params.deliverStatus)
  if (params.itemMatchStatus) query.set('item_match_status', params.itemMatchStatus)
  if (params.zohoSyncStatus) query.set('zoho_sync_status', params.zohoSyncStatus)
  if (params.source) query.set('source', params.source)
  if (params.sortBy) query.set('sort_by', params.sortBy)
  if (params.sortDir) query.set('sort_dir', params.sortDir)
  if (params.orderDateFrom) query.set('order_date_from', params.orderDateFrom)
  if (params.orderDateTo) query.set('order_date_to', params.orderDateTo)

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

export async function updatePurchaseOrder(poId: number, body: PurchaseOrderUpdate): Promise<PurchaseOrder> {
  const { data } = await axiosClient.patch<PurchaseOrder>(PURCHASING.PURCHASE(poId), body)
  return data
}

export async function deletePurchaseOrder(poId: number): Promise<void> {
  await axiosClient.delete(PURCHASING.PURCHASE(poId))
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

export async function importPurchasesFromZoho(params: {
  orderDateFrom: string
  orderDateTo: string
}): Promise<ZohoPurchaseImportResponse> {
  const query = new URLSearchParams()
  query.set('order_date_from', params.orderDateFrom)
  query.set('order_date_to', params.orderDateTo)
  const qs = query.toString()
  const url = qs ? `${PURCHASING.IMPORT_ZOHO}?${qs}` : PURCHASING.IMPORT_ZOHO

  const { data } = await axiosClient.post<ZohoPurchaseImportResponse>(url)
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

export async function importPurchasesFromFile(
  source: PurchaseFileImportSource,
  file: File,
): Promise<PurchaseFileImportResponse> {
  const formData = new FormData()
  formData.append('file', file)
  const { data } = await axiosClient.post<PurchaseFileImportResponse>(
    `${PURCHASING.IMPORT_PURCHASE_FILE}?source=${encodeURIComponent(source)}`,
    formData,
    {
      headers: { 'Content-Type': 'multipart/form-data' },
    },
  )
  return data
}

export async function importPurchasesFromEbay(params: {
  source: 'ebay_mekong' | 'ebay_purchasing' | 'ebay_usav' | 'ebay_dragon'
  orderDateFrom: string
  orderDateTo: string
}): Promise<PurchaseFileImportResponse> {
  const query = new URLSearchParams()
  query.set('source', params.source)
  query.set('order_date_from', params.orderDateFrom)
  query.set('order_date_to', params.orderDateTo)

  const { data } = await axiosClient.post<PurchaseFileImportResponse>(
    `${PURCHASING.IMPORT_EBAY}?${query.toString()}`,
  )
  return data
}
