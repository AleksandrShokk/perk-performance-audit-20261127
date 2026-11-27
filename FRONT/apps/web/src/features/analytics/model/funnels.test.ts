import { summarizeFunnel } from '@app/analytics/funnel'
import { describe, expect, it } from 'vitest'

import type { FunnelReport } from '@app/api'

import { marketplaceFunnels } from './funnels'

function report(
  source: 'wb_funnel' | 'ozon_postings',
  opens: number,
  carts: number,
  orders: number
): FunnelReport {
  return {
    data_source: source,
    currency: 'RUB',
    status: 'ready',
    period_days: 1,
    known_days: 1,
    traffic_known_days: 1,
    totals: {
      opens,
      carts,
      orders,
      impressions: source === 'ozon_postings' ? 1000 : null,
      buyouts: 1,
      cancellations: 1
    }
  } as FunnelReport
}
describe('marketplace funnels', () => {
  it('shows native traffic of both marketplaces without combining incompatible counters', () => {
    const reports = [
      report('wb_funnel', 100, 20, 10),
      report('ozon_postings', 200, 50, 20)
    ]
    const funnels = marketplaceFunnels(
      [{ marketplace: 'wildberries' }, { marketplace: 'ozon' }],
      reports,
      []
    )
    expect(summarizeFunnel(reports).opens).toBeNull()
    expect(funnels[0].totals.opens).toBe('100')
    expect(funnels[1].totals.opens).toBe('200')
    expect(funnels[1].totals.impressions).toBe('1000')
    expect(funnels[1].totals.cartPercent).toBe('25')
    expect(funnels[1].totals.orderPercent).toBe('40')
  })
  it('recomputes percentages from totals within one marketplace', () => {
    const funnels = marketplaceFunnels(
      [{ marketplace: 'ozon' }, { marketplace: 'ozon' }],
      [
        report('ozon_postings', 100, 10, 5),
        report('ozon_postings', 300, 90, 45)
      ],
      []
    )
    expect(funnels).toHaveLength(1)
    expect(funnels[0].totals.cartPercent).toBe('25')
    expect(funnels[0].totals.orderPercent).toBe('50')
  })
  it('keeps a missing store incomplete', () => {
    const funnels = marketplaceFunnels(
      [{ marketplace: 'wildberries' }, { marketplace: 'wildberries' }],
      [report('wb_funnel', 100, 20, 10), undefined],
      []
    )
    expect(funnels[0].totals.complete).toBe(false)
    expect(funnels[0].totals.cartPercent).toBeNull()
  })
})
