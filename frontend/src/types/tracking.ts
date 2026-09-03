/**
 * Types for the server-side tracking status scraper.
 * Mirrors app/modules/tracking/schemas.py.
 */

export type TrackingJobStatus =
  | 'idle'
  | 'running'
  | 'paused_rate_limit'
  | 'completed'
  | 'aborted'
  | 'failed'

export type TrackingItemResult =
  | 'DELIVERED'
  | 'SHIPPING'
  | 'PENDING'
  | 'NOT_FOUND'
  | 'UNKNOWN'
  | 'ERROR'
  | 'RATE_LIMITED'
  | 'SKIPPED_TBA'

export type ProbeResultValue = 'OK' | 'RATE_LIMITED' | 'ERROR' | null

export interface TrackingItem {
  order_number: string
  tracking_number: string
  order_ids: number[]
  result: TrackingItemResult | null
  detail: string | null
  checked_at: string | null
  attempts: number
  parcelsapp_url: string
  changed_order_ids: number[]
}

export interface TrackingJob {
  job_id: string | null
  status: TrackingJobStatus
  started_at: string | null
  finished_at: string | null
  total: number
  processed: number
  remaining: number
  counts: Record<string, number>
  current: TrackingItem | null
  cooldown_until: string | null
  consecutive_rate_limited: number
  auto_probe: boolean
  auto_probe_interval_minutes: number
  last_probe_result: ProbeResultValue
  last_probe_at: string | null
  cancel_requested: boolean
  message: string | null
  last_error: string | null
  /** Distinct order ids whose shipping_status flipped this run → need a Zoho push. */
  changed_order_ids: number[]
  items: TrackingItem[]
}

export interface EligibleCount {
  count: number
}

export interface ProbeResult {
  result: ProbeResultValue
  job: TrackingJob
}

export const TRACKING_JOB_ACTIVE: TrackingJobStatus[] = ['running', 'paused_rate_limit']

export function isTrackingJobActive(job?: TrackingJob | null): boolean {
  return !!job && TRACKING_JOB_ACTIVE.includes(job.status)
}
