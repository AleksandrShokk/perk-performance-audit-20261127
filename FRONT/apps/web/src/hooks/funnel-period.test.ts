import { describe, expect, it } from 'vitest'

import { availableFunnelPeriod, wbHistoryNotice } from './funnel-period'

const range = { date_from: '2025-01-01', date_to: '2026-11-07' }
const first = '2025-11-14'
const bounds = { date_from: first, date_to: range.date_to }

describe('WB selectable history', () => {
  it('clips an old preference without changing the original selection for mixed cabinets', () => {
    expect(availableFunnelPeriod(range, first)).toEqual({
      ...range,
      date_from: first
    })
    expect(range.date_from).toBe('2025-01-01')
    expect(availableFunnelPeriod(range)).toBe(range)
  })
  it('keeps retained older history, and never produces a reversed period', () => {
    expect(availableFunnelPeriod(range, '2024-06-01')).toBe(range)
    expect(
      availableFunnelPeriod({ ...range, date_to: '2025-02-01' }, first)
    ).toEqual({ date_from: first, date_to: first })
  })
  it('only warns when the requested mixed period exceeds WB history', () => {
    expect(wbHistoryNotice(range, [bounds])).toBe('WB учтён с 14.11.2025')
    expect(
      wbHistoryNotice({ ...range, date_from: first }, [bounds])
    ).toBeUndefined()
    expect(wbHistoryNotice(range, [])).toBeUndefined()
    expect(wbHistoryNotice(range, [undefined])).toBeUndefined()
    expect(
      wbHistoryNotice(range, [bounds, { ...bounds, date_from: '2024-06-01' }])
    ).toBe('Часть кабинетов WB учтена с 14.11.2025')
  })
})
