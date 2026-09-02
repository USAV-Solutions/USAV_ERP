/**
 * fba.ts – wrappers for the server-side FBA order import.
 * Backend: app/modules/fba/routes.py
 */
import axiosClient from './axiosClient'
import { FBA } from './endpoints'
import type { FbaAuthCheck, FbaImportJob, FbaPeriodHint } from '../types/fba'

export async function getFbaImportStatus(): Promise<FbaImportJob> {
  const { data } = await axiosClient.get<FbaImportJob>(FBA.IMPORT_STATUS)
  return data
}

export async function startFbaImport(
  allOrdersTxt: File,
  fulfillmentCsv: File,
): Promise<FbaImportJob> {
  const form = new FormData()
  form.append('all_orders_txt', allOrdersTxt)
  form.append('fulfillment_csv', fulfillmentCsv)
  const { data } = await axiosClient.post<FbaImportJob>(FBA.IMPORT_START, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data
}

export async function abortFbaImport(): Promise<FbaImportJob> {
  const { data } = await axiosClient.post<FbaImportJob>(FBA.IMPORT_ABORT)
  return data
}

export async function getFbaPeriodHint(): Promise<FbaPeriodHint> {
  const { data } = await axiosClient.get<FbaPeriodHint>(FBA.IMPORT_PERIOD_HINT)
  return data
}

export async function checkFbaAuth(): Promise<FbaAuthCheck> {
  const { data } = await axiosClient.post<FbaAuthCheck>(FBA.IMPORT_AUTH_CHECK)
  return data
}
