import { reportInterval } from '@app/analytics/polling'
import { useQuery } from '@tanstack/react-query'

import { inventoryOverview } from '@app/api'

import { useStoreScope } from '@/features/workspace/hooks/useStoreScope'

export function useInventoryOverview() {
  const scope = useStoreScope('inventory.read')
  return useQuery({
    queryKey: [...scope.key, 'inventory-overview-v2'],
    queryFn: ({ signal }) =>
      inventoryOverview(
        scope.workspaceId!,
        { store_id: scope.storeId },
        { signal }
      ),
    enabled: scope.enabled,
    refetchInterval: query => reportInterval(query.state.data),
    meta: { persist: false }
  })
}
