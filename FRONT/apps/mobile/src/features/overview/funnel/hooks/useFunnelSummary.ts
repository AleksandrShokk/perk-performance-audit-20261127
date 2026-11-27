import { useQueries } from '@tanstack/react-query'

import type { FunnelSummaryReport } from '@app/api'

import { useAuth } from '@/features/auth/providers/AuthProvider'
import { useWorkspace } from '@/features/workspace/providers/WorkspaceProvider'

import type { DateRange } from '@/lib/dates'
import { type Snapshot, fetchSnapshot, refetchWhileStale } from '@/lib/snapshot'

/** Итоги и проценты не ждут загрузки всех дней текущего и прошлого периодов. */
export function useFunnelSummary(
  range: DateRange,
  ready: boolean,
  previousDays = false
) {
  const { user, status } = useAuth()
  const { workspace, store, stores, allStores, can, accessKey, supports } =
    useWorkspace()
  const selected = supports('analytics')
    ? allStores
      ? stores
      : store
        ? [store]
        : []
    : []
  const queries = useQueries({
    queries: selected.map(item => {
      const key = [
        'user',
        user?.id,
        workspace?.id,
        item.id,
        'funnel-summary-customer-v2',
        previousDays,
        accessKey,
        range.date_from,
        range.date_to
      ]
      return {
        queryKey: key,
        queryFn: ({ signal }: { signal: AbortSignal }) =>
          fetchSnapshot<FunnelSummaryReport>(
            `/api/v1/workspaces/${workspace?.id}/stores/${item.id}/insights/funnel/summary?date_from=${range.date_from}&date_to=${range.date_to}&include_previous_days=${previousDays}`,
            key,
            signal
          ),
        enabled:
          ready &&
          status === 'signedIn' &&
          !!workspace &&
          can('analytics.read'),
        meta: { persist: true },
        refetchInterval: (query: {
          state: { data?: Snapshot<FunnelSummaryReport> }
        }) =>
          query.state.data?.data.error_code
            ? 60000
            : refetchWhileStale(query.state.data) || 60000
      }
    })
  })
  return {
    reports: queries.map(query => query.data?.data),
    error: queries.find(query => query.error)?.error,
    refresh: () => Promise.all(queries.map(query => query.refetch()))
  }
}
