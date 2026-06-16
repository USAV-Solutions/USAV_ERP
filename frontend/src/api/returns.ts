import axiosClient from './axiosClient'
import { RETURNS } from './endpoints'
import type {
  ReturnListResponse,
  ReturnNormalizedStatus,
  ReturnPlatform,
  ReturnRecordDetail,
  ReturnSyncRangeRequest,
  ReturnSyncRequest,
  ReturnSyncResponse,
  ReturnSyncStatusResponse,
  ReturnZohoValidationResponse,
} from '../types/returns'

export interface ListReturnsParams {
  skip?: number
  limit?: number
  platform?: ReturnPlatform
  fulfillment_channel?: string
  normalized_status?: ReturnNormalizedStatus
  source?: string
  ordered_at_from?: string
  ordered_at_to?: string
  event_at_from?: string
  event_at_to?: string
  sort_by?: 'event_at' | 'ordered_at' | 'refunded_amount' | 'external_order_id'
  sort_dir?: 'asc' | 'desc'
  search?: string
}

export async function listReturns(params: ListReturnsParams = {}): Promise<ReturnListResponse> {
  const query = new URLSearchParams()
  if (params.skip !== undefined) query.set('skip', String(params.skip))
  if (params.limit !== undefined) query.set('limit', String(params.limit))
  if (params.platform) query.set('platform', params.platform)
  if (params.fulfillment_channel) query.set('fulfillment_channel', params.fulfillment_channel)
  if (params.normalized_status) query.set('normalized_status', params.normalized_status)
  if (params.source) query.set('source', params.source)
  if (params.ordered_at_from) query.set('ordered_at_from', params.ordered_at_from)
  if (params.ordered_at_to) query.set('ordered_at_to', params.ordered_at_to)
  if (params.event_at_from) query.set('event_at_from', params.event_at_from)
  if (params.event_at_to) query.set('event_at_to', params.event_at_to)
  if (params.sort_by) query.set('sort_by', params.sort_by)
  if (params.sort_dir) query.set('sort_dir', params.sort_dir)
  if (params.search) query.set('search', params.search)

  const qs = query.toString()
  const url = qs ? `${RETURNS.LIST}?${qs}` : RETURNS.LIST
  const { data } = await axiosClient.get<ReturnListResponse>(url)
  return data
}

export async function getReturnRecord(recordId: number): Promise<ReturnRecordDetail> {
  const { data } = await axiosClient.get<ReturnRecordDetail>(RETURNS.RECORD(recordId))
  return data
}

export async function getReturnSyncStatus(): Promise<ReturnSyncStatusResponse> {
  const { data } = await axiosClient.get<ReturnSyncStatusResponse>(RETURNS.SYNC_STATUS)
  return data
}

export async function syncReturns(body: ReturnSyncRequest = {}): Promise<ReturnSyncResponse[]> {
  const { data } = await axiosClient.post<ReturnSyncResponse[]>(RETURNS.SYNC, body)
  return data
}

export async function syncReturnsRange(body: ReturnSyncRangeRequest): Promise<ReturnSyncResponse[]> {
  const { data } = await axiosClient.post<ReturnSyncResponse[]>(RETURNS.SYNC_RANGE, body)
  return data
}

export async function syncReturnToZoho(recordId: number): Promise<ReturnZohoValidationResponse> {
  const { data } = await axiosClient.post<ReturnZohoValidationResponse>(RETURNS.ZOHO_SYNC_RECORD(recordId))
  return data
}

export async function importAmazonReturns(file: File): Promise<ReturnSyncResponse> {
  const formData = new FormData()
  formData.append('file', file)
  const { data } = await axiosClient.post<ReturnSyncResponse>(RETURNS.IMPORT_AMAZON_CSV, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data
}

export async function rematchReturnRecord(recordId: number): Promise<ReturnRecordDetail> {
  const { data } = await axiosClient.post<ReturnRecordDetail>(RETURNS.REMATCH_RECORD(recordId))
  return data
}

