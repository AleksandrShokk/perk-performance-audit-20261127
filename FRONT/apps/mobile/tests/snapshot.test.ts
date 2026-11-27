import { beforeEach, expect, it, vi } from 'vitest'

import { queryClient } from '@/lib/queryClient'
import { fetchSnapshot, refetchWhileStale } from '@/lib/snapshot'

const mock = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('@app/api', () => ({ http: { get: mock.get } }))
vi.mock('@/lib/queryClient', async () => {
  const { QueryClient } = await import('@tanstack/react-query')
  return { queryClient: new QueryClient() }
})

beforeEach(() => {
  vi.clearAllMocks()
  queryClient.clear()
})
const key = ['user', 'seller-1', 'store-1', 'dashboard']
const signal = new AbortController().signal

it('сохраняет ETag вместе с данными', async () => {
  mock.get.mockResolvedValue({
    status: 200,
    data: { amount: '100' },
    headers: { etag: 'v1' }
  })
  expect(await fetchSnapshot('/dashboard', key, signal)).toEqual({
    data: { amount: '100' },
    etag: 'v1'
  })
})

it('304 переиспользует строго свой снимок, передавая If-None-Match', async () => {
  const cached = { data: { amount: '100' }, etag: 'v1' }
  queryClient.setQueryData(key, cached)
  mock.get.mockResolvedValue({ status: 304 })
  expect(await fetchSnapshot('/dashboard', key, signal)).toBe(cached)
  expect(mock.get.mock.calls[0]?.[1].headers).toEqual({ 'If-None-Match': 'v1' })
})

it('304 без своего кэша — ошибка, не пустой отчёт', async () => {
  mock.get.mockResolvedValue({ status: 304 })
  await expect(
    fetchSnapshot('/dashboard', ['other-user'], signal)
  ).rejects.toThrow('304')
})

it('опрашивает устаревший снимок, не стирая прежние данные', () => {
  expect(
    refetchWhileStale({ etag: null, data: { freshness: { stale: true } } })
  ).toBe(60000)
  expect(
    refetchWhileStale({ etag: null, data: { freshness: { stale: false } } })
  ).toBe(false)
})
