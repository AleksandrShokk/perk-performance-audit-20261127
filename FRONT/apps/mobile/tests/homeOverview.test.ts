import { afterEach, describe, expect, it, vi } from 'vitest'

import type {
  FunnelDay,
  FunnelReport,
  FunnelSummaryReport,
  ProfitReport,
  StockForecast
} from '@app/api'

import { summarizeFunnel } from '@/features/overview/funnel/model/funnelMetrics'
import {
  buildHomeSales,
  changePercent,
  homePeriod,
  previousPeriod,
  summarizeStock,
  totalExpenses
} from '@/features/overview/home/model/overviewMetrics'
import { DEFAULT_HOME_FILTERS } from '@/features/overview/home/model/overviewTypes'

afterEach(() => vi.useRealTimers())

function day(date: string, changes: Partial<FunnelDay> = {}): FunnelDay {
  return {
    day: date,
    orders: 1,
    orders_amount: '100',
    opens: 10,
    carts: 2,
    wishlist: 0,
    buyout_percent: '100',
    add_to_cart_percent: '20',
    cart_to_order_percent: '50',
    open_to_order_percent: '10',
    cancellations: 0,
    cancellations_amount: '0',
    buyouts: 1,
    buyouts_amount: '80',
    ...changes
  }
}

function report(daily: FunnelDay[]): FunnelReport {
  return {
    date_from: '2026-10-01',
    date_to: '2026-10-04',
    status: 'ready',
    known_days: daily.length,
    currency: 'RUB',
    buyouts_by: 'order_date',
    buyouts_maturing_from: null,
    period_days: daily.length,
    totals: day('2026-10-04'),
    daily,
    products: [],
    products_truncated: false,
    freshness: { stale: false, computed_at: '2026-10-05T00:00:00Z' }
  }
}

const range = { date_from: '2026-10-03', date_to: '2026-10-04' }
const complete = report([
  day('2026-10-01'),
  day('2026-10-02'),
  day('2026-10-03', { orders: 2, orders_amount: '150' }),
  day('2026-10-04', { orders: 2, orders_amount: '150' })
])

describe('периоды главной', () => {
  it('использует завершённые дни Москвы и равный предыдущий диапазон', () => {
    vi.useFakeTimers().setSystemTime(new Date('2026-10-24T10:00:00Z'))
    expect(homePeriod(14)).toEqual({
      date_from: '2026-10-10',
      date_to: '2026-10-23'
    })
    expect(previousPeriod(homePeriod(14))).toEqual({
      date_from: '2026-09-26',
      date_to: '2026-10-09'
    })
    expect(homePeriod('week')).toEqual({
      date_from: '2026-10-19',
      date_to: '2026-10-23'
    })
  })
  it('в понедельник календарная неделя остаётся непустой', () => {
    vi.useFakeTimers().setSystemTime(new Date('2026-10-26T10:00:00Z'))
    expect(homePeriod('week')).toEqual({
      date_from: '2026-10-19',
      date_to: '2026-10-25'
    })
  })
})

describe('суммы, количества и сравнение', () => {
  it('различает операционные суммы и количества, передаёт количество в подсказку', () => {
    const amounts = buildHomeSales([complete], range, DEFAULT_HOME_FILTERS)
    expect(amounts.ordered).toBe('300')
    expect(amounts.buyouts).toBe('160')
    expect(amounts.orderedChange).toBe('50')
    expect(amounts.buyoutsChange).toBe('0')
    expect(amounts.points[0]).toMatchObject({
      ordered: '150',
      orderedUnits: '2',
      previousOrdered: '100'
    })
    const units = buildHomeSales([complete], range, {
      ...DEFAULT_HOME_FILTERS,
      unit: 'units'
    })
    expect(units.ordered).toBe('4')
    expect(units.orderedChange).toBe('100')
  })
  it('не выдаёт отсутствующий день за ноль и не сравнивает неполный период', () => {
    const result = buildHomeSales(
      [report([day('2026-10-03')])],
      range,
      DEFAULT_HOME_FILTERS
    )
    expect(result.ordered).toBe('100')
    expect(result.points[1]?.ordered).toBeNull()
    expect(result.partial).toBe(true)
    expect(result.orderedChange).toBeNull()
  })
  it('сохраняет подтверждённый ноль и не делит на нулевую базу', () => {
    expect(changePercent('10', '0')).toBeNull()
    expect(changePercent('0', '100')).toBe('-100')
    const zero = report([
      day('2026-10-03', { orders: 0, orders_amount: '0' }),
      day('2026-10-04')
    ])
    expect(
      buildHomeSales([zero], range, DEFAULT_HOME_FILTERS).points[0]?.ordered
    ).toBe('0')
  })
  it('суммирует одну валюту и разделяет разные валюты', () => {
    const sums = buildHomeSales(
      [complete, { ...complete, currency: 'KZT' }],
      range,
      DEFAULT_HOME_FILTERS
    )
    expect(sums.amountsUnavailable).toBe(true)
    expect(sums.ordered).toBeNull()
    const same = buildHomeSales(
      [complete, complete],
      range,
      DEFAULT_HOME_FILTERS
    )
    expect(same.amountsUnavailable).toBe(false)
    expect(same.currency).toBe('RUB')
    expect(same.ordered).toBe('600')
    const units = buildHomeSales([complete, complete], range, {
      ...DEFAULT_HOME_FILTERS,
      unit: 'units'
    })
    expect(units.ordered).toBe('8')
  })
  it('сбой одного магазина не превращается в полный отчёт или скрытый ноль', () => {
    const result = buildHomeSales([complete, undefined], range, {
      ...DEFAULT_HOME_FILTERS,
      unit: 'units'
    })
    expect(result.ordered).toBe('4')
    expect(result.partial).toBe(true)
    expect(result.orderedChange).toBeNull()
  })
  it('суммирует decimal без потери разрядов', () => {
    const precise = report([
      day('2026-10-03', { orders_amount: '9999999999999999.99999' }),
      day('2026-10-04', { orders_amount: '0.00001' })
    ])
    expect(buildHomeSales([precise], range, DEFAULT_HOME_FILTERS).ordered).toBe(
      '10000000000000000'
    )
  })
})

describe('финансы и склад', () => {
  const financial: ProfitReport = {
    date_from: range.date_from,
    date_to: range.date_to,
    currency: 'RUB',
    status: 'ready',
    is_partial: false,
    period_covered: true,
    limit: 100,
    offset: 0,
    summary: {
      total_expenses: '600',
      revenue: '1000',
      profit_before_tax: '400',
      calculation_complete: true,
      cogs: '300',
      external_expenses: '200'
    }
  }
  it('общие расходы не пересчитывают себестоимость повторно', () => {
    expect(totalExpenses(financial)).toBe('600')
    expect(totalExpenses({ ...financial, is_partial: true })).toBeNull()
    expect(
      totalExpenses({
        ...financial,
        summary: { ...financial.summary, calculation_complete: false }
      })
    ).toBe('600')
  })
  it('не считает days_of_cover оборачиваемостью и помечает неполные остатки', () => {
    const forecast: StockForecast = {
      stock_as_of: null,
      observed_days: 30,
      source_stale: false,
      status: 'ready',
      snapshot_day: '2026-10-23',
      window_days: 30,
      items: [],
      counts: {},
      freshness: { stale: false, computed_at: '2026-10-24T00:00:00Z' }
    }
    expect(summarizeStock([forecast, undefined])).toMatchObject({
      units: 0,
      urgent: 0,
      partial: true
    })
    expect(summarizeStock([undefined]).units).toBeNull()
    expect(summarizeStock([forecast])).not.toHaveProperty('turnover')
  })
})

describe('выкупы воронки относятся к заказу', () => {
  it('выкуп 23 октября обновляет заказ 1 октября, а не создаёт продажу 23 октября', () => {
    const october = { date_from: '2026-10-01', date_to: '2026-10-23' }
    const orders = day('2026-10-01', {
      orders: 10,
      orders_amount: '1000',
      buyouts: 9,
      buyouts_amount: '900'
    })
    const result = buildHomeSales(
      [report([orders])],
      october,
      DEFAULT_HOME_FILTERS
    )
    expect(result.points[0]).toMatchObject({
      day: '2026-10-01',
      orderedUnits: '10',
      buyoutUnits: '9',
      buyouts: '900'
    })
    expect(result.points[22]).toMatchObject({
      day: '2026-10-23',
      buyouts: null,
      buyoutUnits: null
    })
  })
  it('новый снимок заменяет прежние значения и не накапливает повторные выкупы', () => {
    const oneDay = { date_from: '2026-10-01', date_to: '2026-10-01' }
    const read = (buyouts: number) =>
      buildHomeSales(
        [report([day('2026-10-01', { orders: 10, buyouts })])],
        oneDay,
        { ...DEFAULT_HOME_FILTERS, unit: 'units' }
      )
    expect(read(9).buyouts).toBe('9')
    expect(read(10).buyouts).toBe('10')
    expect(read(10).buyouts).toBe('10')
  })
  it('отмены и последующие возвраты не вычитаются повторно из выкупов WB', () => {
    const data = report([day('2026-10-03', { buyouts: 9, cancellations: 1 })])
    data.totals = data.daily[0]!
    const result = summarizeFunnel([data])
    expect(result.buyouts).toBe('9')
    expect(result.cancellations).toBe('1')
    expect(result.buyoutPercent).toBe('90')
  })
  it('считает процент по суммарным количествам, а не усредняет проценты магазинов', () => {
    const large = {
      ...complete,
      totals: { ...complete.totals, buyouts: 90, cancellations: 10 }
    }
    const small = {
      ...complete,
      totals: { ...complete.totals, buyouts: 0, cancellations: 1 }
    }
    expect(summarizeFunnel([large, small]).buyoutPercent).toBe('89.1')
    expect(summarizeFunnel([large, undefined]).buyoutPercent).toBeNull()
  })
  it('не придумывает валюту и процент для незагруженной воронки', () => {
    const unknown = { ...complete, currency: null }
    const result = buildHomeSales([unknown], range, DEFAULT_HOME_FILTERS)
    expect(result.amountsUnavailable).toBe(true)
    expect(result.ordered).toBeNull()
    expect(summarizeFunnel([unknown]).ordersAmount).toBeNull()
    expect(summarizeFunnel([undefined]).orders).toBeNull()
    expect(summarizeFunnel([undefined]).buyoutPercent).toBeNull()
  })
})

describe('итоги периода без предыдущих дней графика', () => {
  const summary: FunnelSummaryReport = {
    date_from: range.date_from,
    date_to: range.date_to,
    status: 'ready',
    currency: 'RUB',
    error_code: null,
    totals: day('2026-10-04', {
      orders: 4,
      orders_amount: '300',
      buyouts: 2,
      buyouts_amount: '160'
    }),
    previous: {
      date_from: '2026-10-01',
      date_to: '2026-10-02',
      totals: day('2026-10-02', {
        orders: 2,
        orders_amount: '200',
        buyouts: 2,
        buyouts_amount: '160'
      })
    },
    freshness: { computed_at: '2026-10-05T00:00:00Z', stale: false }
  }

  it('начинает с семи дней', () => {
    expect(DEFAULT_HOME_FILTERS.period).toBe(7)
  })
  it('показывает полные суммы и проценты при одном загруженном дне', () => {
    const result = buildHomeSales(
      [report([day('2026-10-04')])],
      range,
      DEFAULT_HOME_FILTERS,
      [summary]
    )
    expect(result.ordered).toBe('300')
    expect(result.orderedChange).toBe('50')
    expect(result.buyoutsChange).toBe('0')
    expect(result.knownDays).toBe(1)
    expect(result.points[0]?.ordered).toBeNull()
    expect(result.points[0]?.previousOrdered).toBeNull()
  })
  it('показывает итоги ещё до первого столбца и корректно сравнивает количества', () => {
    const result = buildHomeSales(
      [undefined],
      range,
      { ...DEFAULT_HOME_FILTERS, unit: 'units' },
      [summary]
    )
    expect(result.ordered).toBe('4')
    expect(result.orderedChange).toBe('100')
    expect(result.knownDays).toBe(0)
  })
  it('не выдаёт неполные данные нескольких магазинов за полное сравнение', () => {
    const result = buildHomeSales(
      [undefined, undefined],
      range,
      DEFAULT_HOME_FILTERS,
      [summary, undefined]
    )
    expect(result.ordered).toBe('300')
    expect(result.orderedChange).toBeNull()
    expect(result.partial).toBe(true)
  })
  it('не складывает суммы итогов в разных валютах', () => {
    const result = buildHomeSales(
      [undefined, undefined],
      range,
      DEFAULT_HOME_FILTERS,
      [summary, { ...summary, currency: 'KZT' }]
    )
    expect(result.ordered).toBeNull()
    expect(result.amountsUnavailable).toBe(true)
  })
})

it('показывает известную часть цены Ozon, не сравнивая её как полную сумму', () => {
  const data = report([
    day('2026-10-01'),
    day('2026-10-02'),
    day('2026-10-03', {
      orders_amount: '70',
      partial_amounts: ['orders_amount']
    }),
    day('2026-10-04')
  ])
  const sales = buildHomeSales([data], range, DEFAULT_HOME_FILTERS)
  expect(sales.ordered).toBe('170')
  expect(sales.orderedPartial).toBe(true)
  expect(sales.orderedChange).toBeNull()
  expect(sales.points[0]?.partial).toBe(true)
})
