import { QueryClient } from '@tanstack/react-query'
import { afterEach, expect, it, vi } from 'vitest'

import {
  catalogModels,
  financeOverview,
  inventoryOverview,
  inventoryReplenishment
} from '@app/api'

import {
  financeQuery,
  productQuery,
  stockQuery,
  supplyQuery
} from './report-queries'

vi.mock('@app/api', () => ({
  catalogModels: vi.fn(),
  financeOverview: vi.fn(),
  inventoryOverview: vi.fn(),
  inventoryReplenishment: vi.fn()
}))
const scope = {
  userId: 'a',
  workspaceId: 'company',
  accessKey: 'owner',
  storeId: 'store',
  canStock: true
}
const range = { date_from: '2026-10-01', date_to: '2026-10-28' }
afterEach(() => vi.clearAllMocks())
it('navigation consumes prefetched reports without a second request', async () => {
  const client = new QueryClient({
    defaultOptions: { queries: { staleTime: 60000, retry: false } }
  })
  vi.mocked(financeOverview).mockResolvedValue({} as never)
  vi.mocked(inventoryOverview).mockResolvedValue({} as never)
  vi.mocked(catalogModels).mockResolvedValue({} as never)
  vi.mocked(inventoryReplenishment).mockResolvedValue({} as never)
  const params = { target_days: 30, lead_time_days: 7, include_fbs: false }
  const queries = [
    financeQuery(scope, range),
    stockQuery(scope, 'fbo'),
    productQuery(scope, {
      search: '',
      inStock: false,
      missingCost: false,
      page: 0,
      pageSize: 25,
      combined: false
    }),
    supplyQuery(scope, params)
  ]
  for (const query of queries) {
    await client.prefetchQuery(query as never)
    await client.fetchQuery(query as never)
  }
  for (const call of [
    financeOverview,
    inventoryOverview,
    catalogModels,
    inventoryReplenishment
  ])
    expect(call).toHaveBeenCalledTimes(1)
  await client.invalidateQueries({ queryKey: ['user', 'a', 'company'] })
  await client.fetchQuery(financeQuery(scope, range))
  expect(financeOverview).toHaveBeenCalledTimes(2)
  client.clear()
})
it('separates users, permissions, stores, periods and FBS choices', () => {
  const key = financeQuery(scope, range).queryKey
  for (const change of [
    { userId: 'b' },
    { workspaceId: 'other' },
    { accessKey: 'viewer' },
    { storeId: 'other' }
  ])
    expect(financeQuery({ ...scope, ...change }, range).queryKey).not.toEqual(
      key
    )
  expect(
    financeQuery(scope, { ...range, date_to: '2026-10-27' }).queryKey
  ).not.toEqual(key)
  const params = { target_days: 30, lead_time_days: 7, include_fbs: false }
  expect(
    supplyQuery(scope, { ...params, include_fbs: true }).queryKey
  ).not.toEqual(supplyQuery(scope, params).queryKey)
})
