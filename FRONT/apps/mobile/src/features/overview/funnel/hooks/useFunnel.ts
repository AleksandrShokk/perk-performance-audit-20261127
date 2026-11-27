import { useQueries } from '@tanstack/react-query'

import type { FunnelReport } from '@app/api'

import { useAuth } from '@/features/auth/providers/AuthProvider'
import { useWorkspace } from '@/features/workspace/providers/WorkspaceProvider'

import type { DateRange } from '@/lib/dates'
import { type Snapshot, fetchSnapshot, refetchWhileStale } from '@/lib/snapshot'

/** Один источник для главной, заказов, выкупов и отмен. Дни — по дате заказа. */
export function useFunnel(range: DateRange, enabled = true) {
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
        'funnel-customer-v2',
        accessKey,
        range.date_from,
        range.date_to
      ]
      return {
        queryKey: key,
        queryFn: ({ signal }: { signal: AbortSignal }) =>
          fetchSnapshot<FunnelReport>(
            `/api/v1/workspaces/${workspace?.id}/stores/${item.id}/insights/funnel?date_from=${range.date_from}&date_to=${range.date_to}`,
            key,
            signal
          ),
        enabled:
          enabled &&
          status === 'signedIn' &&
          !!workspace &&
          can('analytics.read'),
        meta: { persist: true },
        // Читаем готовый снимок PERK. Обновления площадок запускаются сервером в фоне.
        refetchInterval: (query: {
          state: { data?: Snapshot<FunnelReport> }
        }) =>
          query.state.data?.data.error_code
            ? 60000
            : query.state.data?.data.is_loading
              ? 10000
              : refetchWhileStale(query.state.data) || 60000
      }
    })
  })
  const reports = queries.map(query => query.data?.data)
  return {
    reports,
    stores: selected.map((item, index) => ({
      ...item,
      report: reports[index]
    })),
    scope: `${user?.id}:${workspace?.id}:${selected.map(item => item.id).join(',')}`,
    pending: selected.length > 0 && queries.every(query => query.isPending),
    refreshing: queries.some(query => query.isRefetching),
    stale: reports.some(report => report?.freshness.stale),
    hasData: reports.some(report => (report?.known_days ?? 0) > 0),
    error:
      queries.find(query => query.error)?.error ??
      (reports.some(report => report?.error_code)
        ? new Error(
            'Не удалось обновить заказы Ozon. Предыдущие данные сохранены, повторим загрузку автоматически.'
          )
        : undefined),
    refresh: () => Promise.all(queries.map(query => query.refetch()))
  }
}
