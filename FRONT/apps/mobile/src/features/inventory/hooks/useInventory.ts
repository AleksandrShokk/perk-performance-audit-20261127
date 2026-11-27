import { useInfiniteQuery } from '@tanstack/react-query'

import { inventoryOverview } from '@app/api'

import { useStoreScope } from '@/features/workspace/hooks/useStoreScope'

import { useDebouncedValue } from '@/hooks/useDebouncedValue'

export function useInventory(search: string, inStock: boolean) {
  const scope = useStoreScope('inventory.read')
  const query = useDebouncedValue(search.trim())
  return useInfiniteQuery({
    queryKey: [...scope.key, 'inventory-products-v2', query, inStock],
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) =>
      inventoryOverview(
        scope.workspaceId!,
        {
          store_id: scope.storeId,
          q: query,
          in_stock: inStock,
          limit: 30,
          offset: pageParam
        },
        { signal }
      ),
    getNextPageParam: page =>
      page.offset + page.items.length < page.count
        ? page.offset + page.limit
        : undefined,
    enabled: scope.enabled,
    refetchInterval: query =>
      query.state.data?.pages[0]?.is_loading ? 5000 : 60000,
    meta: { persist: false }
  })
}
