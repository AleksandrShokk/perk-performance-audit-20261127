import { useAuth } from '@/features/auth/providers/AuthProvider'
import { useFinance } from '@/features/finance/hooks/useFinance'
import { storageTotal } from '@/features/finance/model/financeTotals'
import { useInventoryOverview } from '@/features/inventory/hooks/useInventoryOverview'
import { useReplenishment } from '@/features/supplies/hooks/useSupplies'
import { useWorkspace } from '@/features/workspace/providers/WorkspaceProvider'

import { useFunnel } from '../../funnel/hooks/useFunnel'
import { useFunnelSummary } from '../../funnel/hooks/useFunnelSummary'
import { buildHomeSales, homeRequestRanges } from '../model/overviewMetrics'
import type { HomeFilters } from '../model/overviewTypes'

export function useHomeOverview(filters: HomeFilters, ready = true) {
  const { user, status } = useAuth()
  const { workspace, store, stores, allStores, can, supports } = useWorkspace()
  const selected = allStores ? stores : store ? [store] : []
  const enabled = status === 'signedIn' && !!workspace
  const { range, funnelRange, summarySupported } = homeRequestRanges(filters)
  // Финансы всегда за 30 дней и не зависят от фильтров графика.
  const finance = useFinance(30)
  const inventory = useInventoryOverview()
  // Для прошлых дат загружаем и предыдущие дни: по ним считаются проценты.
  const funnel = useFunnel(funnelRange, ready)
  const summary = useFunnelSummary(
    range,
    ready && summarySupported,
    filters.comparison === 'previous'
  )
  const replenishment = useReplenishment()

  return {
    range,
    scope: `${user?.id}:${workspace?.id}:${selected.map(item => item.id).join(',')}`,
    sales: buildHomeSales(
      funnel.reports,
      range,
      filters,
      summarySupported ? summary.reports : undefined
    ),
    salesPending: !ready || funnel.pending,
    salesLoading: funnel.reports.some(report => report?.is_loading),
    summaryLoading: summary.reports.some(
      report => report?.freshness.stale && !report.error_code
    ),
    summaryError: summary.reports.some(report => report?.error_code),
    salesHasData: funnel.hasData,
    salesStale: funnel.stale,
    finance: finance.data,
    storage: storageTotal(finance.data),
    expenses: finance.data?.totals.expenses_before_tax,
    inventory: inventory.data,
    stock: {
      urgent: replenishment.data?.urgent_count ?? null,
      partial: !replenishment.data || replenishment.data.partial,
      stale: replenishment.data?.stale ?? false
    },
    error:
      funnel.error ??
      summary.error ??
      finance.error ??
      inventory.error ??
      replenishment.error,
    refreshing:
      finance.isRefetching || funnel.refreshing || replenishment.isRefetching,
    refresh: () =>
      !enabled || !selected.length
        ? Promise.resolve([])
        : Promise.all([
            ...(supports('finance') && can('finance.read')
              ? [finance.refetch()]
              : []),
            ...(supports('analytics') && can('analytics.read')
              ? [funnel.refresh()]
              : []),
            ...(supports('analytics') &&
            summarySupported &&
            can('analytics.read')
              ? [summary.refresh()]
              : []),
            ...(can('inventory.read')
              ? [
                  inventory.refetch(),
                  ...(supports('supplies') ? [replenishment.refetch()] : [])
                ]
              : [])
          ])
  }
}

export type HomeOverview = ReturnType<typeof useHomeOverview>
