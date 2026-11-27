import { format, parseISO, startOfWeek, subDays } from 'date-fns'
import { Decimal } from 'decimal.js'

import type {
  FunnelDay,
  FunnelReport,
  FunnelSummaryReport,
  ProfitReport,
  StockForecast
} from '@app/api'

import {
  type DateRange,
  HISTORY_START,
  eachDay,
  lastDays,
  toISODate
} from './dates'
import { formatMoney, formatNumber, moneyParts } from './format'
import { funnelCurrency, sumKnown } from './funnel'
import { supportsFunnelSummary } from './periods'
import type {
  ChartUnit,
  HomeFilters,
  HomePeriod,
  HomeSales
} from './sales-types'

const Money = Decimal.clone({ precision: 64 })

/** График использует завершённые московские сутки, как финансовые отчёты PERK. */
export function homePeriod(period: HomePeriod): DateRange {
  if (typeof period === 'object') return period
  if (period !== 'week') return lastDays(period)
  const end = lastDays(1).date_to
  return {
    date_from: format(
      startOfWeek(parseISO(end), { weekStartsOn: 1 }),
      'yyyy-MM-dd'
    ),
    date_to: end
  }
}

/** Ровно столько же дней непосредственно перед выбранным периодом. */
export function previousPeriod(range: DateRange): DateRange {
  const end = subDays(parseISO(range.date_from), 1)
  return {
    date_from: toISODate(subDays(end, eachDay(range).length - 1)),
    date_to: toISODate(end)
  }
}

/** Для прошлых дат быстрых итогов WB нет: сравнение считаем по загруженным дням. */
export function homeRequestRanges(filters: HomeFilters) {
  const range = homePeriod(filters.period)
  const previous = previousPeriod(range)
  const summarySupported = supportsFunnelSummary(range)
  const includePrevious = filters.comparison === 'previous' || !summarySupported
  return {
    range,
    summarySupported,
    funnelRange: {
      date_from: includePrevious
        ? previous.date_from < HISTORY_START
          ? HISTORY_START
          : previous.date_from
        : range.date_from,
      date_to: range.date_to
    }
  }
}

function decimal(value: string | number | null | undefined) {
  if (value == null || value === '') return null
  try {
    const number = new Money(value)
    return number.isFinite() ? number : null
  } catch {
    return null
  }
}

export function changePercent(current: string | null, previous: string | null) {
  const value = decimal(current)
  const base = decimal(previous)
  if (value === null || base === null || base.lte(0)) return null
  return value
    .minus(base)
    .dividedBy(base)
    .times(100)
    .toDecimalPlaces(1)
    .toFixed()
}

export function buildHomeSales(
  reports: (FunnelReport | undefined)[],
  range: DateRange,
  filters: HomeFilters,
  summaries?: (FunnelSummaryReport | undefined)[]
): HomeSales {
  const currentDays = eachDay(range)
  const previousDays = eachDay(previousPeriod(range))
  const indexed = reports.map(
    report => new Map(report?.daily.map(day => [day.day, day]))
  )
  const readySummaries = summaries?.map(report =>
    report?.status === 'ready' ? report : undefined
  )
  const hasCurrentDays = reports.some(report =>
    report?.daily.some(
      day =>
        day.day >= range.date_from &&
        day.day <= range.date_to &&
        day.orders !== null
    )
  )
  const useSummary =
    (readySummaries?.length === reports.length &&
      readySummaries.every(Boolean)) ||
    (!hasCurrentDays && readySummaries?.some(Boolean))
  const loaded = [
    ...reports.filter(report => report && report.known_days > 0),
    ...(readySummaries ?? [])
  ]
  const currency = funnelCurrency(loaded)
  const amountsUnavailable =
    filters.unit === 'amount' && loaded.some(Boolean) && !currency
  const read = (
    day: string,
    field: Exclude<keyof FunnelDay, 'partial_amounts'>
  ) => {
    if (amountsUnavailable && field.endsWith('_amount'))
      return { value: null, complete: false }
    const sum = sumKnown(indexed.map(rows => rows.get(day)?.[field]))
    return {
      ...sum,
      complete:
        sum.complete &&
        indexed.every(rows => !rows.get(day)?.partial_amounts?.includes(field))
    }
  }
  const orderField = filters.unit === 'amount' ? 'orders_amount' : 'orders'
  const buyoutField = filters.unit === 'amount' ? 'buyouts_amount' : 'buyouts'
  const days = currentDays.map((day, index) => {
    const before = previousDays[index]!
    return {
      day,
      previousDay: before,
      ordered: read(day, orderField),
      buyouts: read(day, buyoutField),
      previousOrdered: read(before, orderField),
      previousBuyouts: read(before, buyoutField),
      orderedUnits: read(day, 'orders').value,
      buyoutUnits: read(day, 'buyouts').value
    }
  })
  const total = (
    field: 'ordered' | 'buyouts' | 'previousOrdered' | 'previousBuyouts'
  ) => {
    const sum = sumKnown(days.map(day => day[field].value))
    return {
      ...sum,
      complete: sum.complete && days.every(day => day[field].complete)
    }
  }
  const periodTotal = (
    field: typeof orderField | typeof buyoutField,
    before = false
  ) => {
    if (amountsUnavailable && field.endsWith('_amount'))
      return { value: null, complete: false }
    const sum = sumKnown(
      (readySummaries ?? []).map(
        report => (before ? report?.previous.totals : report?.totals)?.[field]
      )
    )
    return {
      ...sum,
      complete:
        sum.complete &&
        (readySummaries ?? []).every(
          report =>
            !(before ? report?.previous : report)?.partial_amounts?.includes(
              field
            )
        )
    }
  }
  const ordered = useSummary ? periodTotal(orderField) : total('ordered')
  const buyouts = useSummary ? periodTotal(buyoutField) : total('buyouts')
  const beforeOrders = useSummary
    ? periodTotal(orderField, true)
    : total('previousOrdered')
  const beforeBuyouts = useSummary
    ? periodTotal(buyoutField, true)
    : total('previousBuyouts')
  return {
    knownDays: currentDays.filter(day => read(day, 'orders').complete).length,
    points: days.map(day => ({
      ...day,
      ordered: day.ordered.value,
      orderedPartial: !day.ordered.complete,
      buyoutsPartial: !day.buyouts.complete,
      previousOrderedPartial: !day.previousOrdered.complete,
      buyouts: day.buyouts.value,
      previousOrdered: day.previousOrdered.value,
      partial:
        !day.ordered.complete ||
        (filters.comparison === 'previous'
          ? !day.previousOrdered.complete
          : !day.buyouts.complete)
    })),
    ordered: ordered.value,
    buyouts: buyouts.value,
    orderedPartial: filters.unit === 'amount' && !ordered.complete,
    buyoutsPartial: filters.unit === 'amount' && !buyouts.complete,
    orderedChange:
      ordered.complete && beforeOrders.complete
        ? changePercent(ordered.value, beforeOrders.value)
        : null,
    buyoutsChange:
      buyouts.complete && beforeBuyouts.complete
        ? changePercent(buyouts.value, beforeBuyouts.value)
        : null,
    partial:
      !ordered.complete ||
      !buyouts.complete ||
      (filters.comparison === 'previous' && !beforeOrders.complete),
    amountsUnavailable,
    currency
  }
}

/** Валюта подтверждается воронкой WB; неизвестная сумма остаётся прочерком. */
export function formatOrderValue(
  value: string | null,
  unit: ChartUnit,
  currency?: string | null
) {
  return unit === 'units'
    ? `${formatNumber(value)}${value == null ? '' : ' шт.'}`
    : currency
      ? formatMoney(value, currency)
      : moneyParts(value).amount
}

/** Известные расходы показываем и до загрузки себестоимости. */
export function totalExpenses(report: ProfitReport | undefined) {
  const summary = report?.summary
  if (
    report?.status !== 'ready' ||
    !summary ||
    !report.period_covered ||
    report.is_partial
  )
    return null
  return summary.total_expenses ?? null
}

export function summarizeStock(reports: (StockForecast | undefined)[]) {
  const ready = reports.filter(
    (report): report is StockForecast =>
      report?.status === 'ready' && !!report.snapshot_day
  )
  const items = ready.flatMap(report => report.items)
  return {
    units: ready.length
      ? items.reduce((sum, item) => sum + item.stock, 0)
      : null,
    urgent: ready.length
      ? items.filter(item =>
          ['critical', 'low', 'out_of_stock'].includes(item.status)
        ).length
      : null,
    partial:
      ready.length !== reports.length ||
      ready.some(report => report.source_stale),
    stale: ready.some(report => report.freshness.stale || report.source_stale)
  }
}
