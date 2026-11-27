import { expect, it } from 'vitest'

import type { FinanceOverview } from '@app/api'

import { storageTotal } from '@/features/finance/model/financeTotals'

it('uses the server storage total independently of marketplace line names', () => {
  const report = {
    totals: { storage_total: '160.35' },
    groups: []
  } as unknown as FinanceOverview
  expect(storageTotal(report)).toBe('160.35')
})
it('preserves the distinction between unknown and a confirmed zero', () => {
  expect(storageTotal()).toBeNull()
  expect(
    storageTotal({
      totals: { storage_total: null }
    } as unknown as FinanceOverview)
  ).toBeNull()
  expect(
    storageTotal({
      totals: { storage_total: '0.00' }
    } as unknown as FinanceOverview)
  ).toBe('0.00')
})
