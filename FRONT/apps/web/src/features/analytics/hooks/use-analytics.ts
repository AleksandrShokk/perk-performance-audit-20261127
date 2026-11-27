'use client'

import { summarizeFunnel } from '@app/analytics/funnel'
import { homePeriod } from '@app/analytics/sales'

import {
  type DashboardFilters,
  buildChartData
} from '@/features/overview/chart-data'

import { useFunnelReports } from '@/hooks/use-funnel-reports'

import { marketplaceFunnels } from '../model/funnels'
import { analyticsRows } from '../model/products'

export function useAnalytics(filters: DashboardFilters) {
  const queries = useFunnelReports(
    homePeriod(filters.period),
    filters.comparison === 'previous',
    filters.priceBasis
  )
  const { range, minDate, periodPending, historyNotice } = queries
  const reports = queries.current.map(query => query.data)
  const previous = queries.previous.map(query => query.data)
  const summaries = queries.summarySupported
    ? queries.summaries.map(query => query.data)
    : []
  const active = [
    ...queries.availability,
    ...queries.current,
    ...queries.previous,
    ...(queries.summarySupported ? queries.summaries : [])
  ].filter(query => query.isEnabled)
  return {
    range,
    minDate,
    periodPending,
    historyNotice,
    stores: queries.stores,
    hasOzon: queries.stores.some(store => store.marketplace === 'ozon'),
    reports,
    progress: queries.progress.map(query => query.data),
    previous,
    summaries,
    chart: buildChartData(reports, previous, summaries, range),
    totals: summarizeFunnel(reports, summaries),
    funnels: marketplaceFunnels(queries.stores, reports, summaries),
    products: analyticsRows(queries.stores, reports, previous),
    truncated: reports.some(report => report?.products_truncated),
    salesPending:
      queries.stores.length > 0 &&
      !queries.availability.some(query => query.isError) &&
      queries.current.every(
        query => query.isPending || query.data?.status === 'preparing'
      ),
    salesLoading: reports.some(report => report?.is_loading),
    hasData:
      reports.some(report => (report?.known_days ?? 0) > 0) ||
      summaries.some(report => report?.status === 'ready'),
    error:
      active.find(query => query.error)?.error ??
      (reports.some(report => report?.error_code) ||
      summaries.some(report => report?.error_code)
        ? new Error(
            reports.some(
              report =>
                report?.data_source === 'ozon_postings' && report.error_code
            )
              ? 'Не удалось обновить Ozon. Показаны сохранённые данные.'
              : 'Не удалось обновить WB. Показаны сохранённые данные.'
          )
        : null),
    refresh: () => Promise.all(active.map(query => query.refetch()))
  }
}
export type Analytics = ReturnType<typeof useAnalytics>
