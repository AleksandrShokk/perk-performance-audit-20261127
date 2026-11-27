import { useInfiniteQuery, useQueryClient } from '@tanstack/react-query'

import { catalogModels } from '@app/api'

import { useAuth } from '@/features/auth/providers/AuthProvider'
import { useWorkspace } from '@/features/workspace/providers/WorkspaceProvider'

import { useDebouncedValue } from '@/hooks/useDebouncedValue'

export function useProducts(
  search: string,
  inStock: boolean,
  missingCost: boolean
) {
  const { user, status } = useAuth()
  const { workspace, store, allStores, accessKey, can } = useWorkspace()
  const query = useDebouncedValue(search.trim())
  return useInfiniteQuery({
    queryKey: [
      'user',
      user?.id,
      workspace?.id,
      'product-cards-v2',
      store?.id ?? 'all',
      accessKey,
      query,
      inStock,
      missingCost
    ],
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) =>
      catalogModels(
        workspace!.id,
        {
          store_id: allStores ? undefined : store?.id,
          q: query,
          in_stock: inStock,
          missing_cost: missingCost,
          limit: 30,
          offset: pageParam
        },
        { signal }
      ),
    getNextPageParam: page =>
      page.offset + page.items.length < page.total
        ? page.offset + page.limit
        : undefined,
    enabled:
      status === 'signedIn' &&
      !!workspace &&
      (allStores || !!store) &&
      (can('inventory.read') || can('profit.read')),
    refetchInterval: query =>
      query.state.data?.pages[0]?.is_loading ? 5000 : 60000,
    meta: { persist: false }
  })
}

export function useRefreshProducts() {
  const client = useQueryClient()
  const { user } = useAuth()
  const { workspace } = useWorkspace()
  // A changed price affects the catalog, cost history and all financial summaries.
  return () =>
    client.invalidateQueries({ queryKey: ['user', user?.id, workspace?.id] })
}
