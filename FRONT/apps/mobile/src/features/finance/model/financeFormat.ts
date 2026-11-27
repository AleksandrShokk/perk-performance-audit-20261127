import { Decimal } from 'decimal.js'

import { UNKNOWN, currencySymbol } from '@/lib/format'

const Money = Decimal.clone({ precision: 64 })

/** Финансовые суммы показываем с копейками, сохраняя десятичную точность API. */
export function formatFinanceMoney(
  value: string | null | undefined,
  currency: string
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
