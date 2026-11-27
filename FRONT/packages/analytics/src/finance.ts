import { Decimal } from 'decimal.js'

import type { FinanceLine, FinanceOverview } from '@app/api'

const Money = Decimal.clone({ precision: 64 })

/** Share of seller revenue; refunds keep their sign, unknowns stay unknown. */
export function financeShare(
  amount: string | null | undefined,
  revenue: string | null | undefined
) {
  if (amount == null || amount === '' || revenue == null || revenue === '')
    return null
  try {
    const value = new Money(amount)
    const base = new Money(revenue)
    if (!value.isFinite() || !base.isFinite() || base.lte(0)) return null
    return value.div(base).times(100).toFixed(1, Money.ROUND_HALF_EVEN)
  } catch {
    return null
  }
}

export function financeLineShare(
  line: Pick<FinanceLine, 'amount' | 'unit'>,
  revenue: string | null | undefined
) {
  return line.unit == null || line.unit === 'money'
    ? financeShare(line.amount, revenue)
    : null
}

/** Storage is calculated by the server, with the marketplace's own ledger rules. */
export function storageTotal(report?: FinanceOverview) {
  return report?.totals.storage_total ?? null
}
