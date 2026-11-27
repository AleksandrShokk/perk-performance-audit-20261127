import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  homePeriod,
  homeRequestRanges,
  previousPeriod
} from '@/features/overview/home/model/overviewMetrics'
import { DEFAULT_HOME_FILTERS } from '@/features/overview/home/model/overviewTypes'
import {
  rangeError,
  resolvePeriod,
  supportsFunnelSummary
} from '@/features/periods/model/periodRange'

import { eachDay } from '@/lib/dates'

beforeEach(() =>
  vi.useFakeTimers().setSystemTime(new Date('2026-10-27T10:00:00Z'))
)
afterEach(() => vi.useRealTimers())

describe('свои даты', () => {
  const range = { date_from: '2026-10-01', date_to: '2026-10-20' }
  it('сохраняет обе даты включительно и не сдвигает их к сегодняшнему дню', () => {
    expect(resolvePeriod(range)).toEqual(range)
    expect(homePeriod(range)).toEqual(range)
    expect(eachDay(range)).toHaveLength(20)
    expect(previousPeriod(range)).toEqual({
      date_from: '2026-09-11',
      date_to: '2026-09-30'
    })
  })
  it('оставляет быстрые пресеты скользящими', () => {
    expect(resolvePeriod(7)).toEqual({
      date_from: '2026-10-20',
      date_to: '2026-10-26'
    })
  })
  it('разрешает один день и 28 дней, отклоняет 29 дней на главной', () => {
    expect(
      rangeError({ date_from: '2026-10-10', date_to: '2026-10-10' }, 28)
    ).toBeUndefined()
    expect(
      rangeError({ date_from: '2026-09-01', date_to: '2026-09-28' }, 28)
    ).toBeUndefined()
    expect(
      rangeError({ date_from: '2026-09-01', date_to: '2026-09-29' }, 28)
    ).toBeDefined()
  })
  it('проверяет настоящие даты, порядок, историю и завершённые сутки Москвы', () => {
    for (const item of [
      { date_from: '2026-02-30', date_to: '2026-03-02' },
      { date_from: '2026-10-12', date_to: '2026-10-10' },
      { date_from: '2024-01-28', date_to: '2024-01-29' },
      { date_from: '2026-10-26', date_to: '2026-10-27' }
    ])
      expect(rangeError(item)).toBeDefined()
    expect(
      rangeError({ date_from: '2024-02-29', date_to: '2024-02-29' })
    ).toBeUndefined()
    vi.setSystemTime(new Date('2026-10-27T22:01:00Z'))
    expect(
      rangeError({ date_from: '2026-10-27', date_to: '2026-10-27' })
    ).toBeUndefined()
  })
  it('применяет лимит 1100 дней сервера к подробным отчётам', () => {
    expect(
      rangeError({ date_from: '2024-01-29', date_to: '2026-10-26' })
    ).toBeUndefined()
    expect(
      rangeError(
        { date_from: '2024-01-29', date_to: '2027-02-02' },
        1100,
        '2027-02-02'
      )
    ).toBeDefined()
  })
  it('для исторического периода запрашивает равный предыдущий период, даже при сравнении с выкупами', () => {
    expect(
      homeRequestRanges({ ...DEFAULT_HOME_FILTERS, period: range })
    ).toEqual({
      range,
      summarySupported: false,
      funnelRange: { date_from: '2026-09-11', date_to: '2026-10-20' }
    })
    expect(supportsFunnelSummary(range)).toBe(false)
  })
  it('не запускает несовместимые итоги WB и не передаёт даты раньше начала истории', () => {
    const result = homeRequestRanges({
      ...DEFAULT_HOME_FILTERS,
      period: { date_from: '2024-01-29', date_to: '2024-02-04' }
    })
    expect(result.summarySupported).toBe(false)
    expect(result.funnelRange.date_from).toBe('2024-01-29')
  })
  it('сохраняет ускоренную загрузку последних 7 дней', () => {
    const result = homeRequestRanges(DEFAULT_HOME_FILTERS)
    expect(result.summarySupported).toBe(true)
    expect(result.funnelRange).toEqual(result.range)
    expect(
      supportsFunnelSummary({ date_from: '2026-09-27', date_to: '2026-10-26' })
    ).toBe(false)
  })
})
