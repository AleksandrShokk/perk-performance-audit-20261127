import { Decimal } from 'decimal.js'

import type { FunnelFigures, FunnelReport, FunnelSummaryReport } from '@app/api'

const Money = Decimal.clone({ precision: 64 })

/** Неизвестное значение не становится нулём; известная часть имеет флаг полноты. */
export function sumKnown(values: (string | number | null | undefined)[]) {
  const known = values.flatMap(value => {
    if (value == null || value === '') return []
    try {
      const number = new Money(value)
      return number.isFinite() ? [number] : []
    } catch {
      return []
    }
  })
  return {
    value: known.length
      ? known.reduce((sum, value) => sum.plus(value), new Money(0)).toFixed()
      : null,
    complete: values.length > 0 && known.length === values.length
  }
}

/** Суммы разных валют не складываем. Отсутствующий магазин остаётся неполной частью. */
export function funnelCurrency(
  reports: ({ currency: string | null } | undefined)[]
) {
  const loaded = reports.filter(report => !!report)
  const currency = loaded[0]?.currency
  return currency && loaded.every(report => report.currency === currency)
    ? currency
    : null
}

export function summarizeFunnel(
  reports: (FunnelReport | undefined)[],
  summaries: (FunnelSummaryReport | undefined)[] = []
) {
  const sources = reports.map((report, index) => {
    const summary =
      summaries[index]?.status === 'ready' ? summaries[index] : undefined
    if (!report && !summary) return undefined
    return {
      currency: summary ? summary.currency : report!.currency,
      totals: summary ? summary.totals : report!.totals,
      available_metrics: report?.available_metrics,
      partial_amounts: summary
        ? summary.partial_amounts
        : report?.partial_amounts,
      trafficComplete:
        report?.data_source !== 'ozon_postings' ||
        report.traffic_known_days == null ||
        report.traffic_known_days === report.period_days,
      complete:
        !!summary ||
        (report?.status === 'ready' && report.known_days === report.period_days)
    }
  })
  const currency = funnelCurrency(sources)
  const mixed =
    new Set(
      reports
        .filter(Boolean)
        .map(report =>
          report?.data_source === 'ozon_postings' ? 'ozon' : 'wb'
        )
    ).size > 1
  const read = (field: keyof FunnelFigures) =>
    mixed && ['impressions', 'opens', 'carts', 'wishlist'].includes(field)
      ? null
      : sources.some(
            report =>
              report?.available_metrics &&
              !report.available_metrics.includes(field)
          )
        ? null
        : field.endsWith('_amount') && !currency
          ? null
          : sumKnown(sources.map(report => report?.totals[field])).value
  const complete =
    sources.length > 0 && sources.every(report => report?.complete)
  const trafficComplete =
    complete && sources.every(report => report?.trafficComplete)
  const percent = (
    part: string | null,
    whole: string | null,
    covered = complete
  ) =>
    covered && part !== null && whole !== null && new Money(whole).gt(0)
      ? new Money(part).div(whole).times(100).toDecimalPlaces(1).toFixed()
      : null
  const orders = read('orders')
  const buyouts = read('buyouts')
  const cancellations = read('cancellations')
  const opens = read('opens')
  const carts = read('carts')
  // Правило WB: выкупы / (выкупы + отмены и возвраты). Проценты магазинов не усредняем.
  const resolved =
    buyouts !== null && cancellations !== null
      ? new Money(buyouts).plus(cancellations).toFixed()
      : null
  return {
    currency,
    complete,
    orders,
    buyouts,
    cancellations,
    opens,
    impressions: read('impressions'),
    carts,
    wishlist: read('wishlist'),
    ordersAmount: read('orders_amount'),
    ordersAmountPartial: sources.some(report =>
      report?.partial_amounts?.includes('orders_amount')
    ),
    buyoutsAmountPartial: sources.some(report =>
      report?.partial_amounts?.includes('buyouts_amount')
    ),
    cancellationsAmountPartial: sources.some(report =>
      report?.partial_amounts?.includes('cancellations_amount')
    ),
    buyoutsAmount: read('buyouts_amount'),
    cancellationsAmount: read('cancellations_amount'),
    buyoutPercent: percent(buyouts, resolved),
    cartPercent: percent(carts, opens, trafficComplete),
    orderPercent: percent(orders, carts, trafficComplete)
  }
}
