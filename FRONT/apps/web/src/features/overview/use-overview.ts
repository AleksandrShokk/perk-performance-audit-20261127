'use client'

import { lastDays } from '@app/analytics/dates'
import { storageTotal } from '@app/analytics/finance'
import { reportInterval } from '@app/analytics/polling'
import { homePeriod } from '@app/analytics/sales'
import { useQuery } from '@tanstack/react-query'
import { Decimal } from 'decimal.js'

import {
  financeOverview,
  inventoryOverview,
  inventoryReplenishment,
  inventorySupplies
} from '@app/api'

import { useAuth } from '@/features/auth/auth-provider'
import { useCoverageChannel } from '@/features/inventory/hooks/use-coverage-channel'
import { useWorkspace } from '@/features/workspace/workspace-provider'

import { useFunnelReports } from '@/hooks/use-funnel-reports'

import { type DashboardFilters, buildChartData } from './chart-data'

/** Reads cached backend snapshots. Refreshes keep the existing content on screen. */
export function useOverview(filters: DashboardFilters) {
  const scope = useWorkspace()
  const [coverage_channel] = useCoverageChannel()
  const { user } = useAuth()
  const key = [
    'user',
    user?.id,
    scope.workspace?.id,
    scope.accessKey,
    coverage_channel,
    scope.store?.id ?? 'all'
  ]
  const enabled = scope.ready && !!scope.workspace && scope.selected.length > 0
  const {
    range,
    minDate,
    periodPending,
    historyNotice,
    availability,
    stores: analytics,
    current: funnels,
    previous: previousFunnels,
    summaries,
    summarySupported,
    progress
  } = useFunnelReports(
    homePeriod(filters.period),
    filters.comparison === 'previous',
    filters.priceBasis
  )
  const finance = useQuery({
    queryKey: [...key, 'finance', 30],
    queryFn: ({ signal }) =>
      financeOverview(
        scope.workspace!.id,
        { ...lastDays(30), store_id: scope.store?.id },
        { signal }
      ),
    enabled: enabled && scope.can('finance.read'),
    refetchInterval: query => reportInterval(query.state.data)
  })
  const inventory = useQuery({
    queryKey: [...key, 'inventory', coverage_channel],
    queryFn: ({ signal }) =>
      inventoryOverview(
        scope.workspace!.id,
        {
          coverage_channel,
          store_id: scope.store?.id,
          in_stock: true,
          limit: 10
        },
        { signal }
      ),
    enabled: enabled && scope.can('inventory.read'),
    refetchInterval: query => reportInterval(query.state.data)
  })
  const replenishment = useQuery({
    queryKey: [...key, 'replenishment'],
    queryFn: ({ signal }) =>
      inventoryReplenishment(
        scope.workspace!.id,
        { store_id: scope.store?.id, limit: 10 },
        { signal }
      ),
    enabled: enabled && scope.can('inventory.read'),
    refetchInterval: query => reportInterval(query.state.data)
  })
  const supplies = useQuery({
    queryKey: [...key, 'supplies'],
    queryFn: ({ signal }) =>
      inventorySupplies(
        scope.workspace!.id,
        { store_id: scope.store?.id, limit: 10 },
        { signal }
      ),
    enabled: enabled && scope.can('inventory.read'),
    refetchInterval: query => reportInterval(query.state.data)
  })
  const reports = funnels.map(query => query.data)
  const queries = [
    ...availability,
    ...funnels,
    ...previousFunnels,
    ...(summarySupported ? summaries : []),
    finance,
    inventory,
    replenishment,
    supplies
  ]
  return {
    range,
    minDate,
    periodPending,
    historyNotice,
    hasOzon: analytics.some(store => store.marketplace === 'ozon'),
    reports,
    progress: progress.map(query => query.data),
    chart: buildChartData(
      reports,
      previousFunnels.map(query => query.data),
      summarySupported ? summaries.map(query => query.data) : [],
      range
    ),
    products: reports
      .flatMap((report, index) =>
        (report?.products ?? []).map(product => ({
          ...product,
          storeId: analytics[index]!.id,
          storeName: analytics[index]!.name,
          currency: report!.currency,
          marketplace: analytics[index]!.marketplace
        }))
      )
      .sort((a, b) => new Decimal(b.orders ?? 0).comparedTo(a.orders ?? 0)),
    productsTruncated: reports.some(report => report?.products_truncated),
    salesPending:
      analytics.length > 0 &&
      !availability.some(query => query.isError) &&
      funnels.every(
        query => query.isPending || query.data?.status === 'preparing'
      ),
    salesLoading: reports.some(report => report?.is_loading),
    finance,
    inventory,
    replenishment,
    supplies,
    storage: storageTotal(finance.data),
    error: queries.find(query => query.error)?.error,
    refresh: () =>
      Promise.all(
        queries.filter(query => query.isEnabled).map(query => query.refetch())
      )
  }
}
export type Overview = ReturnType<typeof useOverview>
