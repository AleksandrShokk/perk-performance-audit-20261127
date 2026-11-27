'use client'

import { useQuery } from '@tanstack/react-query'

import { supplyPlanGet, supplyPlansList } from '@app/api'

import { useAuth } from '@/features/auth/auth-provider'
import { useWorkspace } from '@/features/workspace/workspace-provider'

import { supplyPageSize } from './use-supplies'

export function usePlans(
  storeId: string | undefined,
  page: number,
  enabled: boolean
) {
  const scope = useWorkspace(),
    { user } = useAuth()
  return useQuery({
    queryKey: [
      'user',
      user?.id,
      scope.workspace?.id,
      'supply-plans',
      scope.accessKey,
      storeId ?? 'all',
      page
    ],
    queryFn: ({ signal }) =>
      supplyPlansList(
        scope.workspace!.id,
        {
          store_id: storeId,
          limit: supplyPageSize,
          offset: page * supplyPageSize
        },
        { signal }
      ),
    enabled:
      enabled && scope.ready && !!scope.workspace && scope.can('inventory.read')
  })
}
export function usePlan(id: string) {
  const scope = useWorkspace(),
    { user } = useAuth()
  return useQuery({
    queryKey: [
      'user',
      user?.id,
      scope.workspace?.id,
      'supply-plan',
      scope.accessKey,
      id
    ],
    queryFn: ({ signal }) => supplyPlanGet(scope.workspace!.id, id, { signal }),
    enabled: scope.ready && !!scope.workspace && scope.can('inventory.read'),
    gcTime: 0,
    refetchOnWindowFocus: false
  })
}
