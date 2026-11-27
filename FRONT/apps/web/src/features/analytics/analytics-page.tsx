'use client'

import { useState } from 'react'

import { AppShell } from '@/components/app-shell'
import { Empty, ErrorNotice, Loading } from '@/components/feedback'
import { Skeleton } from '@/components/ui/skeleton'

import { useAuth } from '@/features/auth/auth-provider'
import { RequireAuth } from '@/features/auth/require-auth'
import { readChartFilters } from '@/features/overview/chart-data'
import { SalesChart } from '@/features/overview/sales-chart'
import { ConnectStore } from '@/features/workspace/connect-store'
import { RefreshDataButton } from '@/features/workspace/refresh-data-button'
import { useWorkspace } from '@/features/workspace/workspace-provider'

import { usePreference } from '@/lib/preferences'

import { AnalyticsDetails } from './components/analytics-details'
import { AnalyticsExport } from './components/analytics-export'
import { AnalyticsTable } from './components/analytics-table'
import { FunnelPanel } from './components/funnel-panel'
import { useAnalytics } from './hooks/use-analytics'
import type { AnalyticsRow } from './model/products'

export function AnalyticsPage() {
  const { user } = useAuth()
  const scope = useWorkspace()
  return (
    <RequireAuth>
      <AnalyticsContent
        key={`${user?.id}:${scope.accessKey}:${scope.store?.id ?? 'all'}`}
      />
    </RequireAuth>
  )
}
function AnalyticsContent() {
  const scope = useWorkspace()
  const { user } = useAuth()
  const [saved, setSaved] = usePreference(`perk.web.analytics.${user?.id}`)
  const filters = readChartFilters(saved)
  const analytics = useAnalytics(filters)
  const effectiveFilters =
    analytics.hasData && !analytics.chart.currency
      ? { ...filters, unit: 'units' as const }
      : filters
  const [refreshError, setRefreshError] = useState<unknown>(null)
  const [selected, setSelected] = useState<AnalyticsRow | null>(null)
  const selection =
    selected &&
    (analytics.products.find(row => row.key === selected.key) ?? selected)
  const canRead = scope.can('analytics.read')
  return (
    <AppShell>
      <div className='page-heading'>
        <h1>Аналитика</h1>
        {canRead && (
          <AnalyticsExport
            range={analytics.range}
            priceBasis={filters.priceBasis}
          />
        )}
        <RefreshDataButton
          onRefresh={analytics.refresh}
          onError={setRefreshError}
          disabled={!canRead}
        />
      </div>
      <ErrorNotice
        error={scope.error ?? refreshError}
        onRetry={() => void scope.refresh()}
      />
      {scope.loading ? (
        <Loading />
      ) : !canRead ? (
        <Empty title='Нет доступа к аналитике' />
      ) : !scope.stores.length ? (
        <section className='surface welcome-card'>
          <h2>Подключите магазин</h2>
          <ConnectStore />
        </section>
      ) : !analytics.stores.length ? (
        <Empty title='Аналитика пока недоступна' />
      ) : (
        <>
          <ErrorNotice
            error={analytics.error}
            onRetry={() => void analytics.refresh()}
          />
          <div className='analytics-overview'>
            <SalesChart
              overview={analytics}
              filters={effectiveFilters}
              showLink={false}
              onChange={next => {
                setSaved(JSON.stringify(next))
                if (
                  JSON.stringify(next.period) !== JSON.stringify(filters.period)
                )
                  setSelected(null)
              }}
            />
            <FunnelPanel
              totals={analytics.totals}
              platforms={analytics.funnels}
              pending={analytics.salesPending && !analytics.hasData}
            />
          </div>
          {analytics.salesPending ? (
            <Skeleton className='h-72 w-full rounded-2xl' />
          ) : !analytics.hasData ? (
            <section className='surface'>
              <Empty
                title={
                  analytics.salesLoading
                    ? 'Загружаем аналитику'
                    : 'Нет данных за период'
                }
              />
            </section>
          ) : (
            <AnalyticsTable
              key={`${analytics.range.date_from}:${analytics.range.date_to}`}
              analytics={analytics}
              unit={effectiveFilters.unit}
              comparison={filters.comparison === 'previous'}
              onOpen={setSelected}
            />
          )}
        </>
      )}
      {selection && canRead && (
        <AnalyticsDetails
          key={selection.key}
          row={selection}
          comparison={filters.comparison === 'previous'}
          onClose={() => setSelected(null)}
        />
      )}
    </AppShell>
  )
}
