import { describe, expect, it } from 'vitest'

import type { ProfitReport } from '@app/api'

import { formatFinanceMoney } from '@/features/finance/model/financeFormat'
import { totalExpenses } from '@/features/overview/home/model/overviewMetrics'

describe('финансовые суммы', () => {
  it('отличает неизвестную сумму от нуля и сохраняет копейки', () => {
    expect(formatFinanceMoney(null, 'RUB')).toBe('—')
    expect(formatFinanceMoney('0', 'RUB')).toBe('0,00 ₽')
    expect(formatFinanceMoney('-1234.565', 'RUB')).toBe('-1\u00a0234,57 ₽')
    expect(formatFinanceMoney('9999999999999999.99', 'RUB')).toBe(
      '9\u00a0999\u00a0999\u00a0999\u00a0999\u00a0999,99 ₽'
    )
    expect(formatFinanceMoney('invalid', 'RUB')).toBe('—')
  })
  it('берёт расходы из новой расшифровки и не выводит их из другой базы выручки', () => {
    const report: ProfitReport = {
      status: 'ready',
      is_partial: false,
      period_covered: true,
      date_from: '2026-10-01',
      date_to: '2026-10-02',
      currency: 'RUB',
      limit: 100,
      offset: 0,
      summary: {
        total_expenses: '415',
        revenue: '800',
        profit_before_tax: '585',
        calculation_complete: true,
        financial_details: { seller_revenue: '1000', total_expenses: '415' }
      }
    }
    expect(totalExpenses(report)).toBe('415')
    report.summary!.total_expenses = null
    expect(totalExpenses(report)).toBeNull()
    report.is_partial = true
    expect(totalExpenses(report)).toBeNull()
  })
})

it('показывает удержания WB и внешние расходы без себестоимости, сохраняя неизвестную прибыль', () => {
  const report: ProfitReport = {
    status: 'ready',
    is_partial: false,
    period_covered: true,
    date_from: '2026-09-26',
    date_to: '2026-10-25',
    currency: 'RUB',
    limit: 100,
    offset: 0,
    summary: {
      total_expenses: '365',
      cogs: null,
      calculation_complete: false,
      profit_before_tax: null,
      external_expenses: '5',
      financial_details: { total_expenses: null, wb_expenses_total: '360' }
    }
  }
  expect(totalExpenses(report)).toBe('365')
  expect(report.summary!.profit_before_tax).toBeNull()
  report.summary!.total_expenses = null
  expect(totalExpenses(report)).toBeNull()
})
