import { financeLineShare, financeShare } from '@app/analytics/finance'
import { formatPercent } from '@app/analytics/format'
import { describe, expect, it } from 'vitest'

describe('each financial expense uses the selected report seller revenue', () => {
  it('uses revenue rather than the parent expense group as denominator', () => {
    expect(financeLineShare({ amount: '125', unit: 'money' }, '1000')).toBe(
      '12.5'
    )
    expect(financeLineShare({ amount: '125' }, '2000')).toBe('6.2')
    expect(financeShare('400', '2000')).toBe('20.0')
  })

  it('keeps refunds negative and a known zero at zero', () => {
    expect(financeLineShare({ amount: '-125' }, '1000')).toBe('-12.5')
    expect(financeLineShare({ amount: '0' }, '1000')).toBe('0.0')
    expect(financeShare('1250', '1000')).toBe('125.0')
  })

  it('does not treat counts or rates as money', () => {
    expect(
      financeLineShare({ amount: '125', unit: 'units' }, '1000')
    ).toBeNull()
    expect(
      financeLineShare({ amount: '12.5', unit: 'percent' }, '1000')
    ).toBeNull()
  })

  it.each([null, undefined, '', '0', '-100', 'NaN', 'Infinity', 'invalid'])(
    'keeps an unknown share when revenue is %s',
    revenue => {
      const share = financeShare('125', revenue)
      expect(share).toBeNull()
      expect(formatPercent(share)).toBe('—')
    }
  )

  it.each([null, undefined, '', 'NaN', 'Infinity', 'invalid'])(
    'keeps an unknown share when amount is %s',
    amount => {
      expect(financeShare(amount, '1000')).toBeNull()
    }
  )

  it('matches server rounding without losing precision on large monetary strings', () => {
    expect(financeShare('125', '2000')).toBe('6.2')
    expect(financeShare('127', '2000')).toBe('6.4')
    expect(
      financeShare(
        '125000000000000000000000000.01',
        '1000000000000000000000000000.08'
      )
    ).toBe('12.5')
    expect(formatPercent(financeShare('125', '1000'))).toBe('12,5%')
  })
})
