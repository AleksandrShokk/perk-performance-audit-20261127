import { reportInterval } from '@app/analytics/polling'
import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { inventoryReplenishment, inventorySupplies } from '@app/api'

import { useStoreScope } from '@/features/workspace/hooks/useStoreScope'
import {
  type StoreFeature,
  supportsFeature
} from '@/features/workspace/model/storeFeatures'
import { useWorkspace } from '@/features/workspace/providers/WorkspaceProvider'

/** Фильтр списка не меняет выбранный магазин и сводку всего бизнеса. */
export function useSupplyStoreFilter(feature: StoreFeature = 'supplies') {
  const { allStores, stores } = useWorkspace()
  const [selectedId, setStoreId] = useState<string>()
  const options = allStores
    ? stores.filter(store => supportsFeature(store, feature))
    : []
  const storeId = options.find(store => store.id === selectedId)?.id
  return { stores: options, storeId, setStoreId }
}

export function useReplenishment(includeFbs = false) {
  const scope = useStoreScope('inventory.read', 'supplies')
  return useQuery({
    queryKey: [...scope.key, 'replenishment', includeFbs],
    queryFn: ({ signal }) =>
      inventoryReplenishment(
        scope.workspaceId!,
        {
          store_id: scope.storeId,
          limit: 3,
          urgent_only: true,
          include_fbs: includeFbs
        },
        { signal }
      ),
    enabled: scope.enabled,
    refetchInterval: query => reportInterval(query.state.data),
    meta: { persist: false }
  })
}

export function useReplenishmentList(
  filterStoreId?: string,
  includeFbs = false
) {
  const scope = useStoreScope('inventory.read', 'supplies')
  const storeId = scope.storeId ?? filterStoreId
  return useInfiniteQuery({
    queryKey: [
      ...scope.key,
      'replenishment',
      'list',
      storeId ?? 'all',
      includeFbs
    ],
    initialPageParam: 0,
    queryFn: ({ signal, pageParam }) =>
      inventoryReplenishment(
        scope.workspaceId!,
        {
          store_id: storeId,
          limit: 30,
          offset: pageParam,
          include_fbs: includeFbs
        },
        { signal }
      ),
    getNextPageParam: page =>
      page.offset + page.items.length < page.count
        ? page.offset + page.limit
        : undefined,
    enabled: scope.enabled,
    refetchInterval: query =>
      query.state.data?.pages[0]?.loading ? 5000 : 60000,
    meta: { persist: false }
  })
}

export function useSupplies(filterStoreId?: string) {
  const scope = useStoreScope('inventory.read', 'supply_history')
  const storeId = scope.storeId ?? filterStoreId
  return useInfiniteQuery({
    queryKey: [...scope.key, 'supplies', 'list', storeId ?? 'all'],
    initialPageParam: 0,
    queryFn: ({ signal, pageParam }) =>
      inventorySupplies(
        scope.workspaceId!,
        { store_id: storeId, limit: 30, offset: pageParam },
        { signal }
      ),
    getNextPageParam: page =>
      page.offset + page.items.length < page.count
        ? page.offset + page.limit
        : undefined,
    enabled: scope.enabled,
    refetchInterval: query =>
      query.state.data?.pages[0]?.loading ? 5000 : 60000,
    meta: { persist: false }
  })
}

export const useWbSupplies = useSupplies
