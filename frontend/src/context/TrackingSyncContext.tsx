/**
 * TrackingSyncContext
 *
 * Holds the shared "monitor panel open?" flag and a single polling query for the
 * tracking scrape job. Because the job runs on the server, the panel can be
 * closed and reopened from anywhere (the navbar chip) without interrupting it.
 *
 * Mounted once, high in the tree (see main.tsx), so <GlobalTrackingChip /> in the
 * navbar and <TrackingSyncPanel /> share one poll.
 */
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { useAuth } from '../hooks/useAuth'
import {
  abortTracking,
  getTrackingStatus,
  probeTracking,
  resumeTracking,
  setAutoProbe,
  startTrackingSync,
} from '../api/tracking'
import { isTrackingJobActive, type TrackingJob } from '../types/tracking'

const TRACKING_JOB_KEY = ['trackingJob'] as const

interface TrackingSyncContextValue {
  job: TrackingJob | undefined
  isLoading: boolean
  panelOpen: boolean
  openPanel: () => void
  closePanel: () => void
  start: () => Promise<TrackingJob>
  probe: () => Promise<unknown>
  resume: () => Promise<TrackingJob>
  abort: () => Promise<TrackingJob>
  toggleAutoProbe: (enabled: boolean) => Promise<TrackingJob>
  isMutating: boolean
}

const TrackingSyncContext = createContext<TrackingSyncContextValue | null>(null)

export function TrackingSyncProvider({ children }: { children: ReactNode }) {
  const { isAuthenticated, hasRole } = useAuth()
  const queryClient = useQueryClient()
  const [panelOpen, setPanelOpen] = useState(false)

  const canUse = isAuthenticated && hasRole(['ADMIN', 'SALES_REP'])

  const query = useQuery({
    queryKey: TRACKING_JOB_KEY,
    queryFn: getTrackingStatus,
    enabled: canUse,
    refetchInterval: (q) =>
      isTrackingJobActive(q.state.data) || panelOpen ? 2500 : false,
    staleTime: 0,
  })

  const setJob = useCallback(
    (job: TrackingJob) => queryClient.setQueryData(TRACKING_JOB_KEY, job),
    [queryClient],
  )

  const startMutation = useMutation({
    mutationFn: startTrackingSync,
    onSuccess: (job) => {
      setJob(job)
      setPanelOpen(true)
    },
  })
  const probeMutation = useMutation({
    mutationFn: probeTracking,
    onSuccess: (res) => setJob(res.job),
  })
  const resumeMutation = useMutation({
    mutationFn: resumeTracking,
    onSuccess: setJob,
  })
  const abortMutation = useMutation({
    mutationFn: abortTracking,
    onSuccess: setJob,
  })
  const autoProbeMutation = useMutation({
    mutationFn: setAutoProbe,
    onSuccess: setJob,
  })

  const value = useMemo<TrackingSyncContextValue>(
    () => ({
      job: query.data,
      isLoading: query.isLoading,
      panelOpen,
      openPanel: () => setPanelOpen(true),
      closePanel: () => setPanelOpen(false),
      start: startMutation.mutateAsync,
      probe: probeMutation.mutateAsync,
      resume: resumeMutation.mutateAsync,
      abort: abortMutation.mutateAsync,
      toggleAutoProbe: autoProbeMutation.mutateAsync,
      isMutating:
        startMutation.isPending ||
        probeMutation.isPending ||
        resumeMutation.isPending ||
        abortMutation.isPending ||
        autoProbeMutation.isPending,
    }),
    [
      query.data,
      query.isLoading,
      panelOpen,
      startMutation.mutateAsync,
      startMutation.isPending,
      probeMutation.mutateAsync,
      probeMutation.isPending,
      resumeMutation.mutateAsync,
      resumeMutation.isPending,
      abortMutation.mutateAsync,
      abortMutation.isPending,
      autoProbeMutation.mutateAsync,
      autoProbeMutation.isPending,
    ],
  )

  return (
    <TrackingSyncContext.Provider value={value}>{children}</TrackingSyncContext.Provider>
  )
}

export function useTrackingSync(): TrackingSyncContextValue {
  const ctx = useContext(TrackingSyncContext)
  if (!ctx) {
    throw new Error('useTrackingSync must be used within a TrackingSyncProvider')
  }
  return ctx
}
