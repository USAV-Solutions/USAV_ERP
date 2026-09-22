/**
 * FbaImportContext
 *
 * Shared "monitor panel open?" flag + a single polling query for the server-side
 * FBA import job. The job runs on the server, so the panel can be closed and
 * reopened anywhere (the navbar chip) without interrupting it.
 *
 * Mounted once, high in the tree (see main.tsx), so <GlobalFbaImportChip /> and
 * <FbaImportPanel /> share one poll.
 */
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { useAuth } from '../hooks/useAuth'
import { abortFbaImport, getFbaImportStatus, startFbaImport } from '../api/fba'
import { isFbaImportActive, type FbaImportJob } from '../types/fba'

const FBA_JOB_KEY = ['fbaImportJob'] as const

interface FbaImportContextValue {
  job: FbaImportJob | undefined
  isLoading: boolean
  panelOpen: boolean
  openPanel: () => void
  closePanel: () => void
  start: (args: { allOrdersTxt: File; fulfillmentCsv: File }) => Promise<FbaImportJob>
  abort: () => Promise<FbaImportJob>
  isMutating: boolean
}

const FbaImportContext = createContext<FbaImportContextValue | null>(null)

export function FbaImportProvider({ children }: { children: ReactNode }) {
  const { isAuthenticated, hasRole } = useAuth()
  const queryClient = useQueryClient()
  const [panelOpen, setPanelOpen] = useState(false)

  const canUse = isAuthenticated && hasRole(['ADMIN', 'SALES_REP'])

  const query = useQuery({
    queryKey: FBA_JOB_KEY,
    queryFn: getFbaImportStatus,
    enabled: canUse,
    refetchInterval: (q) => (isFbaImportActive(q.state.data) || panelOpen ? 2000 : false),
    staleTime: 0,
  })

  const setJob = useCallback(
    (job: FbaImportJob) => queryClient.setQueryData(FBA_JOB_KEY, job),
    [queryClient],
  )

  const startMutation = useMutation({
    mutationFn: ({ allOrdersTxt, fulfillmentCsv }: { allOrdersTxt: File; fulfillmentCsv: File }) =>
      startFbaImport(allOrdersTxt, fulfillmentCsv),
    onSuccess: (job) => {
      setJob(job)
      setPanelOpen(true)
      queryClient.invalidateQueries({ queryKey: ['orders'] })
    },
  })
  const abortMutation = useMutation({ mutationFn: abortFbaImport, onSuccess: setJob })

  const value = useMemo<FbaImportContextValue>(
    () => ({
      job: query.data,
      isLoading: query.isLoading,
      panelOpen,
      openPanel: () => setPanelOpen(true),
      closePanel: () => setPanelOpen(false),
      start: startMutation.mutateAsync,
      abort: abortMutation.mutateAsync,
      isMutating: startMutation.isPending || abortMutation.isPending,
    }),
    [
      query.data,
      query.isLoading,
      panelOpen,
      startMutation.mutateAsync,
      startMutation.isPending,
      abortMutation.mutateAsync,
      abortMutation.isPending,
    ],
  )

  return <FbaImportContext.Provider value={value}>{children}</FbaImportContext.Provider>
}

export function useFbaImport(): FbaImportContextValue {
  const ctx = useContext(FbaImportContext)
  if (!ctx) {
    throw new Error('useFbaImport must be used within a FbaImportProvider')
  }
  return ctx
}
