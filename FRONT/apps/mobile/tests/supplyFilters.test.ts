import { beforeEach, expect, it, vi } from 'vitest'

import {
  useReplenishment,
  useReplenishmentList,
  useSupplyStoreFilter,
  useWbSupplies
} from '@/features/supplies/hooks/useSupplies'

const state = vi.hoisted(() => ({
  scope: {
    key: ['user', 'owner', 'workspace', 'all', 'full'],
    workspaceId: 'workspace',
    storeId: undefined as string | undefined,
    enabled: true
  },
  allStores: true,
  selected: undefined as string | undefined,
  stores: [
    {
      id: 'wb',
      name: 'Одинаковое имя',
      marketplace: 'wildberries',
      features: ['supplies', 'supply_history']
    },
    {
      id: 'ozon',
      name: 'Одинаковое имя',
      marketplace: 'ozon',
      features: ['supplies']
    }
  ]
}))
const calls = vi.hoisted(() => ({
  infinite: vi.fn(),
  summary: vi.fn(),
  replenishment: vi.fn(),
  supplies: vi.fn()
}))

vi.mock('react', () => ({
  useState: () => [
    state.selected,
    (id?: string) => {
      state.selected = id
    }
  ]
}))
vi.mock('@tanstack/react-query', () => ({
  useInfiniteQuery: (options: unknown) => {
    calls.infinite(options)
    return {}
  },
  useQuery: (options: unknown) => {
    calls.summary(options)
    return {}
  }
}))
vi.mock('@app/api', () => ({
  inventoryReplenishment: calls.replenishment,
  inventorySupplies: calls.supplies
}))
vi.mock('@/features/workspace/hooks/useStoreScope', () => ({
  useStoreScope: () => state.scope
}))
vi.mock('@/features/workspace/providers/WorkspaceProvider', () => ({
  useWorkspace: () => ({ allStores: state.allStores, stores: state.stores })
}))

type ListOptions = {
  queryKey: unknown[]
  initialPageParam: number
  enabled: boolean
  queryFn: (context: { signal: AbortSignal; pageParam: number }) => unknown
  getNextPageParam: (page: {
    offset: number
    limit: number
    count: number
    items: unknown[]
  }) => number | undefined
}
const options = () => calls.infinite.mock.lastCall![0] as ListOptions

beforeEach(() => {
  vi.clearAllMocks()
  Object.assign(state.scope, {
    key: ['user', 'owner', 'workspace', 'all', 'full'],
    workspaceId: 'workspace',
    storeId: undefined,
    enabled: true
  })
  state.allStores = true
  state.selected = undefined
})

it.each([
  [useReplenishmentList, calls.replenishment],
  [useWbSupplies, calls.supplies]
])(
  'фильтрует на сервере до пагинации и передаёт отмену запроса',
  async (hook, api) => {
    hook('wb')
    const signal = new AbortController().signal
    await options().queryFn({ signal, pageParam: 30 })
    expect(api).toHaveBeenCalledExactlyOnceWith(
      'workspace',
      {
        store_id: 'wb',
        limit: 30,
        offset: 30
      },
      { signal }
    )
  }
)

it.each([useReplenishmentList, useWbSupplies])(
  'разделяет страницы всех кабинетов и выбранного кабинета',
  hook => {
    hook()
    const all = options().queryKey
    hook('wb')
    const wb = options().queryKey
    hook('ozon')
    expect(options().queryKey).not.toEqual(wb)
    expect(wb).not.toEqual(all)
    expect(options().queryKey.slice(0, state.scope.key.length)).toEqual(
      state.scope.key
    )
    expect(options().initialPageParam).toBe(0)
    expect(
      options().getNextPageParam({
        offset: 0,
        limit: 30,
        count: 31,
        items: Array(30)
      })
    ).toBe(30)
    expect(
      options().getNextPageParam({
        offset: 30,
        limit: 30,
        count: 31,
        items: [1]
      })
    ).toBeUndefined()
  }
)

it.each([useReplenishmentList, useWbSupplies])(
  'выбранный в шапке магазин имеет приоритет над локальным фильтром',
  async hook => {
    state.scope.storeId = 'ozon'
    hook('wb')
    const signal = new AbortController().signal
    await options().queryFn({ signal, pageParam: 0 })
    const api =
      hook === useReplenishmentList ? calls.replenishment : calls.supplies
    expect(api.mock.lastCall?.[1].store_id).toBe('ozon')
  }
)

it('сводка всех кабинетов не сужается фильтром списка', async () => {
  useReplenishmentList('ozon')
  useReplenishment()
  const { queryFn } = calls.summary.mock.lastCall![0]
  const signal = new AbortController().signal
  await queryFn({ signal })
  expect(calls.replenishment).toHaveBeenCalledExactlyOnceWith(
    'workspace',
    {
      store_id: undefined,
      limit: 3,
      urgent_only: true
    },
    { signal }
  )
})

it.each([useReplenishmentList, useWbSupplies])(
  'не включает загрузку при отсутствии доступа',
  hook => {
    state.scope.enabled = false
    hook('wb')
    expect(options().enabled).toBe(false)
  }
)

it('фильтрует по ID кабинета, даже когда названия одинаковые', () => {
  useSupplyStoreFilter().setStoreId('ozon')
  expect(useSupplyStoreFilter()).toMatchObject({
    storeId: 'ozon',
    stores: state.stores
  })
  useSupplyStoreFilter().setStoreId(undefined)
  expect(useSupplyStoreFilter().storeId).toBeUndefined()
})

it('сбрасывает недоступный кабинет и предлагает только поддерживаемые кабинеты', () => {
  state.selected = 'ozon'
  const history = useSupplyStoreFilter('supply_history')
  expect(history.storeId).toBeUndefined()
  expect(history.stores.map(store => store.id)).toEqual(['wb'])
  state.selected = 'removed-store'
  expect(useSupplyStoreFilter().storeId).toBeUndefined()
})

it('локальный фильтр используется только в режиме всех магазинов', () => {
  state.allStores = false
  state.selected = 'wb'
  expect(useSupplyStoreFilter()).toMatchObject({
    storeId: undefined,
    stores: []
  })
})
