import { expect, it } from 'vitest'

import type { FunnelDay, FunnelReport, FunnelSummaryReport } from '@app/api'

import {
  turnoverLabel,
  turnoverTitle
} from '@/features/inventory/model/stockCover'
import { summarizeFunnel } from '@/features/overview/funnel/model/funnelMetrics'
import { buildHomeSales } from '@/features/overview/home/model/overviewMetrics'
import { DEFAULT_HOME_FILTERS } from '@/features/overview/home/model/overviewTypes'

function report(ozon = false): FunnelReport {
  const totals = {
    opens: ozon ? null : 100,
    carts: ozon ? null : 20,
    wishlist: ozon ? null : 5,
    orders: 10,
    buyouts: 8,
    cancellations: 1,
    orders_amount: '100.10',
    buyouts_amount: '80.08',
    cancellations_amount: '10.01',
    add_to_cart_percent: null,
    cart_to_order_percent: null,
    open_to_order_percent: null,
    buyout_percent: null
  }
  return {
    date_from: '2026-10-01',
    date_to: '2026-10-01',
    status: 'ready',
    period_days: 1,
    known_days: 1,
    currency: 'RUB',
    buyouts_by: 'order_date',
    buyouts_maturing_from: null,
    data_source: ozon ? 'ozon_postings' : 'wb_funnel',
    available_metrics: ozon
      ? [
          'orders',
          'buyouts',
          'cancellations',
          'orders_amount',
          'buyouts_amount',
          'cancellations_amount'
        ]
      : null,
    totals,
    daily: [{ day: '2026-10-01', ...totals }],
    products: [],
    products_truncated: false,
    freshness: { computed_at: '2026-10-02T00:00:00Z', stale: false }
  }
}

it('mixed cohorts add comparable counts and money but unavailable funnel metrics remain unknown', () => {
  const totals = summarizeFunnel([report(), report(true)])
  expect(totals.orders).toBe('20')
  expect(totals.buyouts).toBe('16')
  expect(totals.ordersAmount).toBe('200.2')
  expect(totals.opens).toBeNull()
  expect(totals.carts).toBeNull()
  expect(totals.wishlist).toBeNull()
  expect(totals.cartPercent).toBeNull()
  expect(totals.orderPercent).toBeNull()
})

it('an unfinished Ozon summary does not replace already loaded days with a WB-only summary', () => {
  const wb = report(),
    ozon = report(true)
  const summary: FunnelSummaryReport = {
    date_from: wb.date_from,
    date_to: wb.date_to,
    status: 'ready',
    currency: 'RUB',
    totals: { ...wb.totals, orders: 100 },
    previous: {
      date_from: '2026-09-30',
      date_to: '2026-09-30',
      totals: wb.totals
    },
    error_code: null,
    freshness: wb.freshness
  }
  const sales = buildHomeSales(
    [wb, ozon],
    { date_from: wb.date_from, date_to: wb.date_to },
    { ...DEFAULT_HOME_FILTERS, unit: 'units' },
    [summary, undefined]
  )
  expect(sales.ordered).toBe('20')
  expect(sales.points[0]?.ordered).toBe('20')
})

it('unknown cohort days remain gaps and do not become zero sales', () => {
  const ozon = report(true)
  ozon.daily.unshift({
    ...ozon.daily[0],
    day: '2026-09-30',
    orders: null,
    buyouts: null,
    orders_amount: null,
    buyouts_amount: null
  } as FunnelDay)
  const sales = buildHomeSales(
    [ozon],
    { date_from: '2026-09-30', date_to: '2026-10-01' },
    { ...DEFAULT_HOME_FILTERS, unit: 'units' }
  )
  expect(sales.points[0]?.ordered).toBeNull()
  expect(sales.points[1]?.ordered).toBe('10')
})

it('native Ozon FBO coverage is labelled separately from WB and no sales is explicit', () => {
  expect(turnoverTitle('ozon_sales_28d_fbo')).toBe('Запас FBO, дней')
  expect(turnoverTitle('wb_orders_28d')).toBe('Запас в днях')
  expect(turnoverLabel(null, 'no_sales')).toBe('Нет продаж за 28 дней')
  expect(turnoverLabel(null, 'no_data')).toBe('Недостаточно данных')
})
