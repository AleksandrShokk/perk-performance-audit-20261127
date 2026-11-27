import { formatDateRange } from '@app/analytics/format'
import { expect, it } from 'vitest'

import { readChartFilters } from './chart-data'

it('formats the start of WB history as a single date', () => {
  const date = formatDateRange('2025-11-14', '2025-11-14')
  expect(date).not.toContain('–')
  expect(date).toContain('14 ноября 2025')
  expect(formatDateRange('2025-11-14', '2025-11-16')).toContain('14–16')
})
it('keeps an explicit price preference and upgrades old preferences', () => {
  expect(
    readChartFilters(JSON.stringify({ priceBasis: 'seller' })).priceBasis
  ).toBe('seller')
  expect(readChartFilters(JSON.stringify({ period: 7 })).priceBasis).toBe(
    'customer'
  )
  expect(
    readChartFilters(JSON.stringify({ priceBasis: 'unknown' })).priceBasis
  ).toBe('customer')
})
