/**
 * tracking.ts – wrappers for the server-side tracking status scraper.
 * Backend: app/modules/tracking/routes.py
 */
import axiosClient from './axiosClient'
import { TRACKING } from './endpoints'
import type { EligibleCount, ProbeResult, TrackingJob } from '../types/tracking'

export async function getEligibleCount(): Promise<EligibleCount> {
  const { data } = await axiosClient.get<EligibleCount>(TRACKING.ELIGIBLE)
  return data
}

export async function getTrackingStatus(): Promise<TrackingJob> {
  const { data } = await axiosClient.get<TrackingJob>(TRACKING.SYNC_STATUS)
  return data
}

export async function startTrackingSync(): Promise<TrackingJob> {
  const { data } = await axiosClient.post<TrackingJob>(TRACKING.SYNC_START)
  return data
}

export async function probeTracking(): Promise<ProbeResult> {
  const { data } = await axiosClient.post<ProbeResult>(TRACKING.SYNC_PROBE)
  return data
}

export async function resumeTracking(): Promise<TrackingJob> {
  const { data } = await axiosClient.post<TrackingJob>(TRACKING.SYNC_RESUME)
  return data
}

export async function abortTracking(): Promise<TrackingJob> {
  const { data } = await axiosClient.post<TrackingJob>(TRACKING.SYNC_ABORT)
  return data
}

export async function setAutoProbe(enabled: boolean): Promise<TrackingJob> {
  const { data } = await axiosClient.patch<TrackingJob>(TRACKING.SYNC_AUTO_PROBE, { enabled })
  return data
}
