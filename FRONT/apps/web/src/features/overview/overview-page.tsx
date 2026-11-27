'use client'

import { Package } from 'lucide-react'
import { useState } from 'react'

import { AppShell } from '@/components/app-shell'
import { Empty, ErrorNotice, Loading } from '@/components/feedback'

import { useAuth } from '@/features/auth/auth-provider'
import { RequireAuth } from '@/features/auth/require-auth'
import { ConnectStore } from '@/features/workspace/connect-store'
import { RefreshDataButton } from '@/features/workspace/refresh-data-button'
import { useWorkspace } from '@/features/workspace/workspace-provider'

import { usePreference } from '@/lib/preferences'

import { AttentionPanel } from './attention-panel'
import { readChartFilters } from './chart-data'
import { FinanceCard } from './finance-card'
import { OverviewTable, type TableTab } from './overview-table'
import { SalesChart } from './sales-chart'
import { useOverview } from './use-overview'

export function OverviewPage() {
  const { user } = useAuth()
  return (
    <RequireAuth>
      <Dashboard key={user?.id} />
    </RequireAuth>
  )
}
function Dashboard() {
  const scope = useWorkspace()
  const { user } = useAuth()
  const [preference, setPreference] = usePreference(`perk.web.home.${user?.id}`)
  const filters = readChartFilters(preference)
  const overview = useOverview(filters)
  const [refreshError, setRefreshError] = useState<unknown>(null)
  const [selectedTab, setSelectedTab] = useState<TableTab>('products')
  const tab = scope.can(
    selectedTab === 'products' ? 'analytics.read' : 'inventory.read'
  )
    ? selectedTab
    : scope.can('analytics.read')
      ? 'products'
      : 'inventory'
  const onTab = (next: TableTab) => {
    setSelectedTab(next)
    document
      .getElementById('reports')
      ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
  const canReports = scope.can('analytics.read') || scope.can('inventory.read')
  return (
    <AppShell>
      <div
        className='page-heading'
        id='overview'
      >
        <h1 className='sr-only'>Обзор</h1>
        <RefreshDataButton
          key={`${scope.accessKey}:${scope.store?.id ?? 'all'}`}
          onRefresh={overview.refresh}
          onError={setRefreshError}
        />
      </div>
      <ErrorNotice
        error={scope.error ?? overview.error ?? refreshError}
        onRetry={() =>
          void Promise.all([scope.refresh(), overview.refresh()]).catch(
            setRefreshError
          )
        }
      />
      {scope.loading ? (
        <Loading />
      ) : !scope.stores.length ? (
        <div className='surface welcome-card'>
          <span className='welcome-icon'>
            <Package size={32} />
          </span>
          <h2>Подключите первый магазин</h2>
          <ConnectStore />
          {!scope.admin && (
            <p className='muted'>Обратитесь к администратору компании</p>
          )}
        </div>
      ) : (
        <div className='dashboard-content'>
          {(scope.can('analytics.read') || scope.can('inventory.read')) && (
            <div
              className={
                scope.can('analytics.read') && scope.can('inventory.read')
                  ? 'dashboard-top'
                  : 'dashboard-top single'
              }
            >
              {scope.can('analytics.read') && (
                <SalesChart
                  overview={overview}
                  filters={filters}
                  onChange={next => setPreference(JSON.stringify(next))}
                />
              )}
              {scope.can('inventory.read') && (
                <AttentionPanel
                  overview={overview}
                  onTab={onTab}
                />
              )}
            </div>
          )}
          {scope.can('finance.read') && <FinanceCard overview={overview} />}
          {canReports && (
            <OverviewTable
              overview={overview}
              tab={tab}
              onTab={setSelectedTab}
            />
          )}
          {!canReports && !scope.can('finance.read') && (
            <Empty title='Нет доступа к отчётам' />
          )}
        </div>
      )}
    </AppShell>
  )
}
