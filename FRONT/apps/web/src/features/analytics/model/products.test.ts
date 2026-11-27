import { summarizeFunnel } from '@app/analytics/funnel'
import { describe, expect, it } from 'vitest'

import type { FunnelReport, FunnelSummaryReport } from '@app/api'

import { analyticsRows, productChange, selectAnalyticsRows } from './products'

function report(currency = 'RUB', orders = 10): FunnelReport {
  const totals = {
    opens: 100,
    carts: 20,
    orders,
    buyouts: 8,
    cancellations: 2,
    wishlist: null,
    orders_amount: '1000',
    buyouts_amount: '800',
    cancellations_amount: '200',
    add_to_cart_percent: '20',
    cart_to_order_percent: '50',
    open_to_order_percent: '10',
    buyout_percent: '80'
  }
  return {
    date_from: '2026-11-01',
    date_to: '2026-11-01',
    status: 'ready',
    period_days: 1,
    known_days: 1,
    currency,
    buyouts_by: 'order_date',
    buyouts_maturing_from: null,
    totals,
    daily: [],
    products: [
      {
        ...totals,
        nm_id: '',
        marketplace_code: '9001',
        title: 'Helmet',
        barcodes: ['000101']
      }
    ],
    products_truncated: false,
    freshness: { computed_at: '2026-11-06T12:00:00Z', stale: false }
  }
}
describe('analytics data semantics', () => {
  it('keeps identical native IDs independent in different cabinets', () => {
    const rows = analyticsRows(
      [
        { id: 'one', name: 'One', marketplace: 'ozon' },
        { id: 'two', name: 'Two', marketplace: 'ozon' }
      ],
      [report(), report()],
      []
    )
    expect(rows[0]!.key).not.toBe(rows[1]!.key)
    expect(rows).toHaveLength(2)
    expect(
      selectAnalyticsRows(rows, '000101', 'two', 'orders', true, 'units')
    ).toHaveLength(1)
  })
  it('requires complete, comparable periods and a positive baseline for growth', () => {
    const [row] = analyticsRows(
      [{ id: 'one', name: 'One', marketplace: 'ozon' }],
      [report('RUB', 10)],
      [report('RUB', 8)]
    )
    expect(productChange(row!, 'orders', 'units')).toBe('25')
    expect(
      productChange({ ...row!, complete: false }, 'orders', 'units')
    ).toBeNull()
    expect(
      productChange({ ...row!, previousCurrency: 'KZT' }, 'orders', 'amount')
    ).toBeNull()
    expect(
      productChange(
        {
          ...row!,
          current: { ...row!.current, partial_amounts: ['orders_amount'] }
        },
        'orders',
        'amount'
      )
    ).toBeNull()
    expect(
      productChange(
        { ...row!, previous: { ...row!.previous!, orders: 0 } },
        'orders',
        'units'
      )
    ).toBeNull()
  })
  it('does not average per-store percentages or sum different currencies', () => {
    const second = report('KZT', 20)
    second.totals.buyouts = 2
    second.totals.cancellations = 8
    const summary = summarizeFunnel([report(), second])
    expect(summary.orders).toBe('30')
    expect(summary.ordersAmount).toBeNull()
    expect(summary.buyoutPercent).toBe('50')
  })
  it('uses a ready summary without inventing complete daily coverage', () => {
    const daily = { ...report(), status: 'partial' as const, known_days: 0 }
    const fast: FunnelSummaryReport = {
      date_from: daily.date_from,
      date_to: daily.date_to,
      status: 'ready',
      currency: 'RUB',
      totals: report().totals,
      previous: {
        date_from: '2026-10-31',
        date_to: '2026-10-31',
        totals: report().totals
      },
      error_code: null,
      freshness: daily.freshness
    }
    expect(summarizeFunnel([daily], [fast]).complete).toBe(true)
    expect(daily.known_days).toBe(0)
    expect(summarizeFunnel([daily]).buyoutPercent).toBeNull()
  })
  it('preserves unavailable metrics and sorts missing values last without mutation', () => {
    const missing = {
      ...report(),
      available_metrics: ['orders', 'buyouts', 'cancellations']
    }
    expect(summarizeFunnel([missing]).opens).toBeNull()
    const rows = analyticsRows(
      [{ id: 'one', name: 'One', marketplace: 'ozon' }],
      [report()],
      []
    )
    const list = [
      {
        ...rows[0]!,
        key: 'unknown',
        current: { ...rows[0]!.current, orders: null }
      },
      rows[0]!
    ]
    expect(
      selectAnalyticsRows(list, '', '', 'orders', false, 'units')[1]!.key
    ).toBe('unknown')
    expect(list[0]!.key).toBe('unknown')
  })
})
