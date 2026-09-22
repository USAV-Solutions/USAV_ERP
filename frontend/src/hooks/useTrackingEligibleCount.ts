/**
 * Fetches the count of orders eligible for a tracking-status check.
 * Used to badge the "Check Tracking Statuses" trigger. Only fetches when enabled
 * (e.g. when the Sale Actions menu is open).
 */
import { useQuery } from '@tanstack/react-query'
import { getEligibleCount } from '../api/tracking'

export function useTrackingEligibleCount(enabled: boolean) {
  const query = useQuery({
    queryKey: ['trackingEligibleCount'],
    queryFn: getEligibleCount,
    enabled,
    staleTime: 30_000,
  })
  return { count: query.data?.count, isLoading: query.isLoading }
}
