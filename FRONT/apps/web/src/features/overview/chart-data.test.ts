import { describe, expect, it } from 'vitest'

import type { FunnelFigures, FunnelReport, FunnelSummaryReport } from '@app/api'

import { buildChartData } from './chart-data'

const range = { date_from: '2026-10-20', date_to: '2026-10-21' }

it('does not compare historical money in a different currency', () => {
  const current = report([
    { day: '2026-10-20', orders: 3 },
    { day: '2026-10-21', orders: 7 }
  ])
  const past = report(
    [
      { day: '2026-10-18', orders: 2 },
      { day: '2026-10-19', orders: 3 }
    ],
    'KZT'
  )
  const chart = buildChartData([current], [past], [], range)
  expect(chart.metrics[0].amount.value).toBe('1000')
  expect(chart.metrics[0].amountChange).toBeNull()
  expect(chart.points[0].values.orders.previousAmount).toBeNull()
  expect(chart.metrics[0].unitsChange).toBe('100')
})
function figures(orders: number, amount = String(orders * 100)): FunnelFigures {
  return {
    orders,
    orders_amount: amount,
    buyouts: orders,
    buyouts_amount: amount,
    cancellations: 1,
    cancellations_amount: '100',
    opens: null,
    carts: null,
    wishlist: null,
    add_to_cart_percent: null,
    cart_to_order_percent: null,
    open_to_order_percent: null,
    buyout_percent: null
  }
}
function report(
  days: { day: string; orders: number }[],
  currency = 'RUB'
): FunnelReport {
  return {
    ...range,
    status: 'ready',
    period_days: 2,
    known_days: days.length,
    currency,
    buyouts_by: 'order_date',
    buyouts_maturing_from: null,
    totals: figures(999),
    daily: days.map(day => ({ ...figures(day.orders), day: day.day })),
    products: [],
    products_truncated: false,
    freshness: { stale: false, computed_at: '2026-10-22T00:00:00Z' }
  }
}
describe('desktop chart snapshots', () => {
  it('isolates the selected period and aligns previous days by position', () => {
    const current = report([
      { day: '2026-10-19', orders: 900 },
      { day: '2026-10-20', orders: 3 },
      { day: '2026-10-21', orders: 7 }
    ])
    const past = report([
      { day: '2026-10-18', orders: 2 },
      { day: '2026-10-19', orders: 3 }
    ])
    const chart = buildChartData([current], [past], [], range)
    expect(chart.metrics[0].units.value).toBe('10')
    expect(chart.metrics[0].unitsChange).toBe('100')
    expect(chart.points[0].values.orders.previousUnits).toBe('2')
    expect(chart.points[1].values.orders.previousUnits).toBe('3')
  })
  it('keeps unknown days as gaps and suppresses incomplete comparisons', () => {
    const chart = buildChartData(
      [report([{ day: '2026-10-20', orders: 3 }])],
      [
        report([
          { day: '2026-10-18', orders: 2 },
          { day: '2026-10-19', orders: 3 }
        ])
      ],
      [],
      range
    )
    expect(chart.points[1].values.orders.units).toBeNull()
    expect(chart.metrics[0].units.value).toBe('3')
    expect(chart.metrics[0].unitsChange).toBeNull()
  })
  it('marks a known-price subtotal incomplete instead of comparing it as a total', () => {
    const source = report([
      { day: '2026-10-20', orders: 3 },
      { day: '2026-10-21', orders: 7 }
    ])
    source.daily[0]!.partial_amounts = ['orders_amount']
    const chart = buildChartData(
      [source],
      [
        report([
          { day: '2026-10-18', orders: 2 },
          { day: '2026-10-19', orders: 3 }
        ])
      ],
      [],
      range
    )
    expect(chart.metrics[0].amount.value).toBe('1000')
    expect(chart.metrics[0].amount.complete).toBe(false)
    expect(chart.points[0].values.orders.amountComplete).toBe(false)
    expect(chart.points[1].values.orders.amountComplete).toBe(true)
    expect(chart.metrics[0].amountChange).toBeNull()
    expect(chart.metrics[0].unitsChange).toBe('100')
  })
  it('never adds money across currencies but keeps comparable quantities', () => {
    const chart = buildChartData(
      [
        report([{ day: '2026-10-20', orders: 3 }]),
        report([{ day: '2026-10-20', orders: 4 }], 'KZT')
      ],
      [],
      [],
      range
    )
    expect(chart.metrics[0].amount.value).toBeNull()
    expect(chart.points[0].values.orders.amount).toBeNull()
    expect(chart.points[0].values.orders.units).toBe('7')
  })
  it('uses ready summary totals before daily details arrive, including cancellations', () => {
    const summary: FunnelSummaryReport = {
      ...range,
      totals: figures(10),
      previous: { ...range, totals: figures(5) },
      status: 'ready',
      currency: 'RUB',
      error_code: null,
      freshness: { computed_at: '2026-10-22T00:00:00Z', stale: false }
    }
    const chart = buildChartData([undefined], [], [summary], range)
    expect(chart.metrics[0].units.value).toBe('10')
    expect(chart.metrics[0].unitsChange).toBe('100')
    expect(chart.metrics[2].amount.value).toBe('100')
    expect(chart.points[0].values.orders.units).toBeNull()
  })
})

it('retains received Ozon money and keeps partial traffic out of full-period ratios', async () => {
  const { summarizeFunnel } = await import('@app/analytics/funnel')
  const current = report([
    { day: '2026-10-20', orders: 3 },
    { day: '2026-10-21', orders: 7 }
  ])
  current.data_source = 'ozon_postings'
  current.traffic_known_days = 1
  current.available_metrics = [
    'orders',
    'buyouts',
    'cancellations',
    'orders_amount',
    'buyouts_amount',
    'cancellations_amount',
    'opens',
    'carts'
  ]
  current.totals = { ...figures(10), opens: 100, carts: 20 }
  const summary = summarizeFunnel([current])
  expect(summary.ordersAmount).toBe('1000')
  expect(summary.opens).toBe('100')
  expect(summary.cartPercent).toBeNull()
  expect(summary.orderPercent).toBeNull()
  expect(summary.buyoutPercent).not.toBeNull()
})
