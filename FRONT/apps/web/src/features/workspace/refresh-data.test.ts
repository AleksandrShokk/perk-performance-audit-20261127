import { beforeEach, expect, it, vi } from 'vitest'

import { type StoreResponse, storeRefreshData } from '@app/api'

import { refreshSelectedStores } from './refresh-data'

vi.mock('@app/api', () => ({ storeRefreshData: vi.fn() }))
const refresh = vi.mocked(storeRefreshData)
const store = (id: string, connection_status = 'connected') =>
  ({ id, connection_status }) as StoreResponse

beforeEach(() => refresh.mockReset())

it('обновляет только выбранные подключённые кабинеты', async () => {
  const signal = new AbortController().signal
  await refreshSelectedStores(
    'company',
    [store('wb'), store('ozon'), store('off', 'disconnected')],
    signal
  )
  expect(refresh.mock.calls.map(call => call.slice(0, 2))).toEqual([
    ['company', 'wb'],
    ['company', 'ozon']
  ])
  expect(refresh.mock.calls[0]?.[2]).toEqual({ signal })
})

it('ошибка одного кабинета не мешает запустить остальные', async () => {
  refresh.mockRejectedValueOnce(new Error('Ошибка WB'))
  const result = refreshSelectedStores(
    'company',
    [store('wb'), store('ozon')],
    new AbortController().signal
  )
  await expect(result).rejects.toThrow('Ошибка WB')
  expect(refresh).toHaveBeenCalledTimes(2)
})
