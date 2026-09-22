/**
 * useOrderZohoSync – queue a set of orders for outbound Zoho sync, then poll
 * their sync status to completion.
 *
 * Extracted from the "Range Sync" flow in OrdersManagement so it can be reused
 * (e.g. as the final step of the tracking scrape in TrackingSyncPanel). The
 * caller resolves *which* order ids to sync; this hook does queue + poll +
 * progress reporting.
 */
import { useCallback, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { forceSyncOrder, getOrderSyncStatuses } from '../api/sync'

export type ZohoSyncPhase = 'idle' | 'queueing' | 'polling' | 'done'

export interface ZohoSyncProgress {
  total: number
  pending: number // still QUEUED on the Zoho side
  syncing: number
  synced: number
  failed: number
}

const ZERO: ZohoSyncProgress = { total: 0, pending: 0, syncing: 0, synced: 0, failed: 0 }
const MAX_POLLS = 40
const POLL_MS = 1000

function errText(e: unknown): string {
  const anyErr = e as { response?: { data?: { detail?: string } }; message?: string }
  return anyErr?.response?.data?.detail || anyErr?.message || 'request failed'
}

export function useOrderZohoSync() {
  const queryClient = useQueryClient()
  const [phase, setPhase] = useState<ZohoSyncPhase>('idle')
  const [progress, setProgress] = useState<ZohoSyncProgress>(ZERO)
  const [failures, setFailures] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const runningRef = useRef(false)

  const reset = useCallback(() => {
    setPhase('idle')
    setProgress(ZERO)
    setFailures([])
    setError(null)
  }, [])

  const run = useCallback(
    async (orderIds: number[]) => {
      if (runningRef.current || !orderIds.length) return
      runningRef.current = true

      const total = orderIds.length
      setError(null)
      setFailures([])
      setProgress({ ...ZERO, total })
      setPhase('queueing')

      const queued: number[] = []
      const queueFailures: string[] = []
      for (const id of orderIds) {
        try {
          await forceSyncOrder(id)
          queued.push(id)
        } catch (e) {
          queueFailures.push(`Order #${id}: ${errText(e)}`)
        }
        setProgress((p) => ({
          ...p,
          pending: queued.length,
          failed: queueFailures.length,
        }))
      }
      setFailures(queueFailures)

      if (!queued.length) {
        setError('No orders could be queued for Zoho sync.')
        setPhase('done')
        runningRef.current = false
        return
      }

      setPhase('polling')
      let settled = false
      for (let attempt = 0; attempt < MAX_POLLS; attempt += 1) {
        const statuses = await getOrderSyncStatuses(queued)
        const byId = new Map(statuses.map((s) => [s.id, s]))
        let pending = 0
        let syncing = 0
        let synced = 0
        const pollFailures: string[] = []

        for (const id of queued) {
          const s = byId.get(id)
          if (!s) {
            pollFailures.push(`Order #${id}: sync status not found`)
          } else if (s.status === 'SYNCED') {
            synced += 1
          } else if (s.status === 'ERROR') {
            pollFailures.push(`Order #${id}: ${s.error || 'Zoho sync failed'}`)
          } else if (s.status === 'QUEUED') {
            pending += 1
          } else {
            syncing += 1
          }
        }

        setProgress({
          total,
          pending,
          syncing,
          synced,
          failed: queueFailures.length + pollFailures.length,
        })
        setFailures([...queueFailures, ...pollFailures].slice(0, 100))
        queryClient.invalidateQueries({ queryKey: ['orders'] })

        if (pending === 0 && syncing === 0) {
          settled = true
          break
        }
        await new Promise((r) => window.setTimeout(r, POLL_MS))
      }

      if (!settled) {
        setError('Some orders are still queued/syncing on Zoho — check the Zoho Sync column.')
      }
      setPhase('done')
      runningRef.current = false
    },
    [queryClient],
  )

  return {
    phase,
    progress,
    failures,
    error,
    run,
    reset,
    isRunning: phase === 'queueing' || phase === 'polling',
  }
}
