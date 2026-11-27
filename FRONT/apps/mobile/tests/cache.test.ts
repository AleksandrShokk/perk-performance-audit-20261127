import { QueryClient, dehydrate } from '@tanstack/react-query'
import { beforeEach, expect, it, vi } from 'vitest'

import { persistOptions, queryClient, resetQueryCache } from '@/lib/queryClient'

const storage = vi.hoisted(() => ({
  getItem: vi.fn(),
  setItem: vi.fn(),
  removeItem: vi.fn()
}))
vi.mock('@react-native-async-storage/async-storage', () => ({
  default: storage
}))

beforeEach(() => {
  vi.clearAllMocks()
  queryClient.clear()
})

it('не сохраняет на диск отчёты и профиль даже при старой метке persist', () => {
  const client = new QueryClient()
  const reportKey = ['user', 'seller-1', 'store-1', 'dashboard']
  client.setQueryDefaults(reportKey, { meta: { persist: true } })
  client.setQueryData(reportKey, { revenue: '100' })
  client.setQueryData(['auth', 'me'], { email: 'private@example.test' })
  const saved = dehydrate(client, persistOptions.dehydrateOptions)
  expect(saved.queries).toEqual([])
  expect(JSON.stringify(saved)).not.toContain('revenue')
  expect(JSON.stringify(saved)).not.toContain('private@example.test')
  expect(saved.mutations).toEqual([])
  client.clear()
})

it('выход очищает память и сохранённый кэш', async () => {
  queryClient.setQueryData(['user', 'seller-1', 'store-1'], { revenue: '100' })
  await resetQueryCache()
  expect(queryClient.getQueryCache().getAll()).toHaveLength(0)
  expect(storage.removeItem).toHaveBeenCalledWith('perk.query-cache')
})

it('отложенная запись отчёта не возвращает данные на диск после выхода', async () => {
  await resetQueryCache()
  vi.useFakeTimers()
  try {
    storage.setItem.mockResolvedValue(undefined)
    const client = {
      timestamp: Date.now(),
      buster: 'v1',
      clientState: { queries: [], mutations: [] }
    }
    await persistOptions.persister.persistClient(client)
    const delayed = persistOptions.persister.persistClient({
      ...client,
      timestamp: Date.now() + 1
    })
    await resetQueryCache()
    await vi.runAllTimersAsync()
    await delayed
    expect(storage.setItem).toHaveBeenCalledTimes(1)
    expect(storage.removeItem).toHaveBeenCalledWith('perk.query-cache')
  } finally {
    vi.useRealTimers()
  }
})
