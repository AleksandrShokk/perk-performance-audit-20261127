'use client'

import { reportInterval } from '@app/analytics/polling'
import { useQuery } from '@tanstack/react-query'

import type { SupplyParameters } from '@app/schemas'

import { inventorySupplies } from '@app/api'

import { useAuth } from '@/features/auth/auth-provider'
import { useWorkspace } from '@/features/workspace/workspace-provider'

import { supplyQuery } from '@/lib/report-queries'

export type SupplyView =
  'recommendations' | 'history' | 'plans' | 'destinations'
export const supplyPageSize = 20
function poll(data?: { loading: boolean }) {
  return reportInterval(data)
}
export function useSupplies(
  view: SupplyView,
  filter: string,
  page: number,
  urgent: boolean,
  parameters: SupplyParameters
) {
  const scope = useWorkspace()
  const { user } = useAuth()
  const canRecommendations = scope.selected.some(store =>
    store.features.includes('supplies')
  )
  const canHistory = scope.selected.some(store =>
    store.features.includes('supply_history')
  )
  const feature = view === 'history' ? 'supply_history' : 'supplies'
  const stores = scope.selected.filter(store =>
    store.features.includes(feature)
  )
  const filterId = !scope.store && stores.find(store => store.id === filter)?.id
  const storeId = scope.store?.id || filterId || undefined
  const enabled =
    scope.ready && !!scope.workspace && scope.can('inventory.read')
  const key = [
    'user',
    user?.id,
    scope.workspace?.id,
    'supplies-page',
    scope.accessKey
  ]
  const source = {
    userId: user?.id,
    workspaceId: scope.workspace?.id,
    accessKey: scope.accessKey,
    storeId: scope.store?.id,
    canStock: scope.can('inventory.read')
  }
  const summary = useQuery({
    ...supplyQuery(source, parameters),
    enabled: enabled && canRecommendations,
    refetchInterval: query => poll(query.state.data)
  })
  const recommendations = useQuery({
    ...supplyQuery(source, parameters, { storeId, urgent, page }),
    enabled: enabled && canRecommendations && view === 'recommendations',
    refetchInterval: query => poll(query.state.data)
  })
  const history = useQuery({
    queryKey: [...key, 'history', storeId ?? 'all', page],
    queryFn: ({ signal }) =>
      inventorySupplies(
        scope.workspace!.id,
        {
          store_id: storeId,
          limit: supplyPageSize,
          offset: page * supplyPageSize
        },
        { signal }
      ),
    enabled: enabled && canHistory && view === 'history',
    refetchInterval: query => poll(query.state.data)
  })
  return {
    summary,
    recommendations,
    history,
    canRecommendations,
    canHistory,
    stores,
    filterId,
    storeId,
    fetching:
      summary.isFetching ||
      (view === 'history'
        ? history.isFetching
        : view === 'recommendations' && recommendations.isFetching)
  }
}
