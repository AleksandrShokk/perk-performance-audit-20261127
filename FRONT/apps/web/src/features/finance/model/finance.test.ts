import { describe, expect, it } from 'vitest'

import type { FinanceOverview } from '@app/api'

import { summaryCSV } from './download'
import { financeLineValue, financeMoney } from './finance-format'
import { expenseSchema, taxSchema } from './forms'

const report: FinanceOverview = {
  date_from: '2025-01-01',
  date_to: '2026-10-28',
  currency: 'RUB',
  updated_at: null,
  is_partial: true,
  is_loading: true,
  period_covered: false,
  expenses_exclude_cogs: true,
  total_stores: 1,
  totals: {
    seller_revenue: '1234567890123456.125',
    marketplace_revenue: null,
    expenses_before_tax: null,
    profit_before_tax: '0',
    settlement: '-12.34'
  },
  groups: [
    {
      key: 'sales',
      title: '=HYPERLINK("http://test.invalid")',
      amount: '10',
      share_percent: null,
      lines: []
    },
    {
      key: 'cogs',
      title: 'Себестоимость',
      amount: '3',
      share_percent: null,
      lines: []
    }
  ],
  taxes: {
    configured_stores: 0,
    total_stores: 1,
    vat: null,
    tax: null,
    net_profit: null,
    notes: []
  }
}

describe('financial display and export', () => {
  it('retains decimal precision in large totals and rounds at half a kopeck', () => {
    expect(financeMoney('1234567890123456.125')).toBe(
      '1\u00a0234\u00a0567\u00a0890\u00a0123\u00a0456,13 ₽'
    )
    expect(financeMoney('-0.125')).toBe('-0,13 ₽')
    expect(financeMoney('0')).toBe('0,00 ₽')
    expect(financeMoney(null)).toBe('—')
    expect(financeMoney('NaN')).toBe('—')
  })
  it('uses the unit of a detail line instead of interpreting counts as money', () => {
    expect(
      financeLineValue(
        { key: 'units', title: '', amount: '42', unit: 'units' },
        'RUB'
      )
    ).toBe('42 шт.')
    expect(
      financeLineValue(
        { key: 'rate', title: '', amount: '12.5', unit: 'percent' },
        'RUB'
      )
    ).toBe('12,5%')
  })
  it('exports the API values, retains unknowns and flags partial reports', () => {
    const csv = summaryCSV(report, 'Тест', true)
    expect(csv).toContain('"Расходы";"";"RUB"')
    expect(csv).toContain('"Прибыль до налогов";"0";"RUB"')
    expect(csv).toContain('"К перечислению";"-12,34";"RUB"')
    expect(csv).toContain('"1234567890123456,125"')
    expect(csv).toContain('Частичный отчёт')
  })
  it('neutralizes spreadsheet formulas in marketplace text and excludes restricted fields', () => {
    const csv = summaryCSV(report, '+SUM(1;2)', false)
    expect(csv).toContain('"\'+SUM(1;2)"')
    expect(csv).toContain("'=HYPERLINK")
    expect(csv).not.toContain('Себестоимость')
    expect(csv).not.toContain('Прибыль до налогов')
  })
})
describe('finance inputs', () => {
  it('normalizes a decimal comma without converting money to a floating point number', () => {
    const result = expenseSchema.parse({
      amount: ' 999999999999,1234 ',
      expense_date: '2026-10-28',
      category: 'other',
      comment: ' Аренда '
    })
    expect(result.amount).toBe('999999999999.1234')
    expect(result.comment).toBe('Аренда')
    for (const amount of ['0', '-1', 'Infinity', '2e3', '1.00001'])
      expect(expenseSchema.safeParse({ ...result, amount }).success).toBe(false)
  })
  it('rejects impossible dates, rates above 100 and contradictory disabled tax settings', () => {
    const tax = {
      effective_from: '2026-10-01',
      regime: 'usn_income',
      rate: '6,5',
      vat_rate: '0',
      income_base: 'revenue'
    }
    expect(taxSchema.parse(tax).rate).toBe('6.5')
    expect(taxSchema.safeParse({ ...tax, rate: '101' }).success).toBe(false)
    expect(taxSchema.safeParse({ ...tax, regime: 'none' }).success).toBe(false)
    expect(
      taxSchema.safeParse({ ...tax, effective_from: '2026-02-31' }).success
    ).toBe(false)
  })
})
