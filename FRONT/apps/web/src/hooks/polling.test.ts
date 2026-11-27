import { progressInterval, reportInterval } from '@app/analytics/polling'
import { expect, it } from 'vitest'

it('backs off unchanged reports and limits progress traffic for multiple cabinets', () => {
  expect(reportInterval({ freshness: { stale: true } })).toBe(60_000)
  expect(reportInterval({ is_loading: true })).toBe(10_000)
  expect(reportInterval({ status: 'preparing' })).toBe(10_000)
  expect(reportInterval({ is_partial: true })).toBe(10_000)
  expect(reportInterval({ is_loading: true, error_code: 'invalid' })).toBe(
    60_000
  )
  expect(progressInterval(0, 2, 20_000)).toBe(5000)
  expect(progressInterval(0, 2, 61_000)).toBe(15_000)
  expect(progressInterval(0, 10, 20_000)).toBe(25_000)
})
