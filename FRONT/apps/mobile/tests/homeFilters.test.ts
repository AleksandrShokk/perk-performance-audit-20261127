import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useHomeFilters } from '@/features/overview/home/hooks/useHomeFilters'

const harness = vi.hoisted(() => ({
  userId: 'first' as string | undefined,
  state: undefined as unknown,
  effect: undefined as (() => void | (() => void)) | undefined,
  storage: new Map<string, string>(),
  getItem: vi.fn(),
  setItem: vi.fn()
}))

vi.mock('react', () => ({
  useState: (initial: unknown) => {
    harness.state ??= initial
    return [
      harness.state,
      (next: unknown) => {
        harness.state = typeof next === 'function' ? next(harness.state) : next
      }
    ]
  },
  useEffect: (effect: () => void | (() => void)) => {
    harness.effect = effect
  }
}))
vi.mock('@react-native-async-storage/async-storage', () => ({
  default: { getItem: harness.getItem, setItem: harness.setItem }
}))
vi.mock('@/features/auth/providers/AuthProvider', () => ({
  useAuth: () => ({ user: harness.userId ? { id: harness.userId } : undefined })
}))

const first = 'perk.home-filters.first'
const second = 'perk.home-filters.second'
const stored = (period: 7 | 14 | 28) =>
  JSON.stringify({ period, unit: 'amount', comparison: 'buyouts' })
const flush = () => vi.waitFor(() => expect(useHomeFilters().ready).toBe(true))

beforeEach(() => {
  harness.userId = 'first'
  harness.state = undefined
  harness.storage.clear()
  harness.getItem
    .mockReset()
    .mockImplementation(async (key: string) => harness.storage.get(key) ?? null)
  harness.setItem
    .mockReset()
    .mockImplementation(async (key: string, value: string) => {
      harness.storage.set(key, value)
    })
})

describe('сохранение фильтров главной', () => {
  it('первый запуск использует 7 дней и ждёт чтения настроек', async () => {
    expect(useHomeFilters().ready).toBe(false)
    harness.effect?.()
    await flush()
    expect(useHomeFilters().filters.period).toBe(7)
  })
  it('восстанавливает выбранные 28 дней после повторного открытия', async () => {
    useHomeFilters().setFilters({
      period: 28,
      unit: 'units',
      comparison: 'buyouts'
    })
    await vi.waitFor(() => expect(harness.storage.has(first)).toBe(true))
    harness.state = undefined
    useHomeFilters()
    harness.effect?.()
    await flush()
    expect(useHomeFilters().filters).toEqual({
      period: 28,
      unit: 'units',
      comparison: 'buyouts'
    })
  })
  it('не переносит фильтры в другой аккаунт', async () => {
    harness.storage.set(first, stored(28))
    harness.storage.set(second, stored(14))
    useHomeFilters()
    const cleanup = harness.effect?.()
    await flush()
    expect(useHomeFilters().filters.period).toBe(28)
    if (cleanup) cleanup()
    harness.userId = 'second'
    expect(useHomeFilters().filters.period).toBe(7)
    expect(useHomeFilters().ready).toBe(false)
    harness.effect?.()
    await flush()
    expect(useHomeFilters().filters.period).toBe(14)
  })
  it('позднее чтение настроек не отменяет новый выбор', async () => {
    let resolve!: (value: string) => void
    harness.getItem.mockImplementationOnce(
      () =>
        new Promise<string>(done => {
          resolve = done
        })
    )
    const hook = useHomeFilters()
    harness.effect?.()
    hook.setFilters({ period: 28, unit: 'amount', comparison: 'buyouts' })
    resolve(stored(7))
    await flush()
    expect(useHomeFilters().filters.period).toBe(28)
  })
  it('повреждённые настройки возвращают начальные 7 дней', async () => {
    harness.storage.set(first, '{broken')
    useHomeFilters()
    harness.effect?.()
    await flush()
    expect(useHomeFilters().filters.period).toBe(7)
  })
})

it('восстанавливает свой диапазон без замены скользящим периодом', async () => {
  const period = { date_from: '2025-10-01', date_to: '2025-10-20' }
  useHomeFilters().setFilters({
    period,
    unit: 'amount',
    comparison: 'previous'
  })
  await vi.waitFor(() => expect(harness.storage.has(first)).toBe(true))
  harness.state = undefined
  useHomeFilters()
  harness.effect?.()
  await flush()
  expect(useHomeFilters().filters.period).toEqual(period)
})

it('отклоняет сохранённый диапазон длиннее 28 дней', async () => {
  harness.storage.set(
    first,
    JSON.stringify({
      period: { date_from: '2025-10-01', date_to: '2025-10-31' },
      unit: 'amount',
      comparison: 'previous'
    })
  )
  useHomeFilters()
  harness.effect?.()
  await flush()
  expect(useHomeFilters().filters.period).toBe(7)
})
