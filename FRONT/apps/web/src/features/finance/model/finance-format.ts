import { UNKNOWN, currencySymbol } from '@app/analytics/format'
import { formatNumber, formatPercent } from '@app/analytics/format'
import { Decimal } from 'decimal.js'

import type { FinanceLine } from '@app/api'

const Money = Decimal.clone({ precision: 64 })

export function financeMoney(
  value: string | null | undefined,
  currency = 'RUB'
) {
  if (value == null || value === '') return UNKNOWN
  try {
    const number = new Money(value)
    if (!number.isFinite()) return UNKNOWN
    const [whole, cents] = number.toFixed(2, Money.ROUND_HALF_UP).split('.')
    return `${whole!.replace(/\B(?=(\d{3})+(?!\d))/g, '\u00a0')},${cents} ${currencySymbol(currency)}`
  } catch {
    return UNKNOWN
  }
}
export function financeLineValue(line: FinanceLine, currency: string) {
  return line.unit === 'units'
    ? line.amount == null
      ? UNKNOWN
      : `${formatNumber(line.amount)} шт.`
    : line.unit === 'percent'
      ? formatPercent(line.amount)
      : financeMoney(line.amount, currency)
}
