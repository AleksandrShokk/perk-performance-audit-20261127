import { type DateRange, eachDay } from '@app/analytics/dates'
import { funnelCurrency, sumKnown } from '@app/analytics/funnel'
import { rangeError } from '@app/analytics/periods'
import { changePercent, previousPeriod } from '@app/analytics/sales'
import type { HomePeriod } from '@app/analytics/sales-types'

import type { FunnelFigures, FunnelReport, FunnelSummaryReport } from '@app/api'

export const metrics = [
  { key: 'orders', label: 'Заказано' },
  { key: 'buyouts', label: 'Выкуплено' },
  { key: 'cancellations', label: 'Отмены и возвраты' }
] as const
export type Metric = (typeof metrics)[number]['key']
export type DashboardFilters = {
  period: HomePeriod
  metric: Metric
  unit: 'amount' | 'units'
  comparison: 'previous' | 'none'
  priceBasis?: 'customer' | 'seller'
}
export const defaultFilters: DashboardFilters = {
  period: 7,
  metric: 'orders',
  unit: 'amount',
  comparison: 'previous',
  priceBasis: 'customer'
}

/** Unknown days remain gaps. A percentage requires complete values on both sides. */
export function buildChartData(
  reports: (FunnelReport | undefined)[],
  previous: (FunnelReport | undefined)[],
  summaries: (FunnelSummaryReport | undefined)[],
  range: DateRange
) {
  const currency = funnelCurrency([
    ...reports.filter(report => report && report.known_days > 0),
    ...summaries.filter(report => report?.status === 'ready')
  ])
  const indexes = new Map(
    [...reports, ...previous].flatMap(report =>
      report
        ? [[report, new Map(report.daily.map(row => [row.day, row]))] as const]
        : []
    )
  )
  const days = eachDay(range)
  const before = eachDay(previousPeriod(range))
  const read = (
    sources: (FunnelReport | undefined)[],
    day: string,
    field: keyof FunnelFigures
  ) => {
    const rows = sources.map(report =>
      report ? indexes.get(report)?.get(day) : undefined
    )
    const unavailable = sources.some(
      report =>
        report?.available_metrics && !report.available_metrics.includes(field)
    )
    const sameCurrency =
      !field.endsWith('_amount') ||
      (!!currency &&
        sources.every(
          report =>
            !report || report.known_days === 0 || report.currency === currency
        ))
    const sum = sumKnown(rows.map(row => row?.[field]))
    return {
      value: unavailable || !sameCurrency ? null : sum.value,
      complete:
        !unavailable &&
        sameCurrency &&
        sum.complete &&
        rows.every(row => !row?.partial_amounts?.includes(field))
    }
  }
  const readySummaries = summaries.map(report =>
    report?.status === 'ready' ? report : undefined
  )
  const useSummary =
    readySummaries.length === reports.length &&
    readySummaries.length > 0 &&
    readySummaries.every(Boolean)
  const total = (field: keyof FunnelFigures, past = false) => {
    if (field.endsWith('_amount') && !currency)
      return { value: null, complete: false }
    if (useSummary) {
      const rows = readySummaries.map(report =>
        past ? report?.previous : report
      )
      const sum = sumKnown(rows.map(row => row?.totals[field]))
      return {
        ...sum,
        complete:
          sum.complete &&
          rows.every(row => !row?.partial_amounts?.includes(field))
      }
    }
    const values = (past ? before : days).map(day =>
      read(past ? previous : reports, day, field)
    )
    return {
      ...sumKnown(values.map(value => value.value)),
      complete: values.every(value => value.complete)
    }
  }
  return {
    currency,
    metrics: metrics.map(metric => {
      const amount = total(`${metric.key}_amount`)
      const units = total(metric.key)
      const previousAmount = total(`${metric.key}_amount`, true)
      const previousUnits = total(metric.key, true)
      return {
        ...metric,
        amount,
        units,
        amountChange:
          amount.complete && previousAmount.complete
            ? changePercent(amount.value, previousAmount.value)
            : null,
        unitsChange:
          units.complete && previousUnits.complete
            ? changePercent(units.value, previousUnits.value)
            : null
      }
    }),
    points: days.map((day, index) => ({
      day,
      previousDay: before[index]!,
      values: Object.fromEntries(
        metrics.map(({ key }) => {
          const amount = read(reports, day, `${key}_amount`)
          const previousAmount = read(previous, before[index]!, `${key}_amount`)
          return [
            key,
            {
              amount: amount.value,
              amountComplete: amount.complete,
              units: read(reports, day, key).value,
              previousAmount: previousAmount.value,
              previousAmountComplete: previousAmount.complete,
              previousUnits: read(previous, before[index]!, key).value
            }
          ]
        })
      ) as Record<
        Metric,
        {
          amount: string | null
          amountComplete: boolean
          previousAmountComplete: boolean
          units: string | null
          previousAmount: string | null
          previousUnits: string | null
        }
      >
    }))
  }
}
export type ChartData = ReturnType<typeof buildChartData>

/** Only UI preferences are persisted; report data stays in the user-scoped cache. */
export function readChartFilters(raw: string | null): DashboardFilters {
  if (!raw) return defaultFilters
  try {
    const value = JSON.parse(raw)
    return {
      period: [7, 14, 28].includes(value.period)
        ? value.period
        : value.period &&
            typeof value.period === 'object' &&
            !rangeError(value.period, 1100)
          ? value.period
          : 7,
      unit: value.unit === 'units' ? 'units' : 'amount',
      metric: ['orders', 'buyouts', 'cancellations'].includes(value.metric)
        ? value.metric
        : 'orders',
      comparison: value.comparison === 'none' ? 'none' : 'previous',
      priceBasis: value.priceBasis === 'seller' ? 'seller' : 'customer'
    }
  } catch {
    return defaultFilters
  }
}
