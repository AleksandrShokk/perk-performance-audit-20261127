'use client'

import { reportInterval } from '@app/analytics/polling'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import type { SupplyParameters } from '@app/schemas'

import {
  type SupplyDestination,
  inventoryDestinations,
  inventoryDestinationsRefresh,
  inventoryReplenishment
} from '@app/api'

import { useAuth } from '@/features/auth/auth-provider'
import { useWorkspace } from '@/features/workspace/workspace-provider'

import { useProtectedAction } from '@/hooks/use-protected-action'

export function useDestinations({
  storeId,
  selected,
  parameters,
  page,
  urgent
}: {
  storeId?: string
  selected: SupplyDestination | null
  parameters: SupplyParameters
  page: number
  urgent: boolean
}) {
  const scope = useWorkspace(),
    { user } = useAuth(),
    client = useQueryClient()
  const key = [
    'user',
    user?.id,
    scope.workspace?.id,
    'supply-destinations',
    scope.accessKey,
    storeId ?? 'all'
  ]
  const list = useQuery({
    queryKey: [...key, 'list', parameters],
    queryFn: ({ signal }) =>
      inventoryDestinations(
        scope.workspace!.id,
        { ...parameters, store_id: storeId },
        { signal }
      ),
    refetchInterval: query => reportInterval(query.state.data)
  })
  const refresh = useProtectedAction(
    signal =>
      inventoryDestinationsRefresh(
        scope.workspace!.id,
        { store_id: storeId },
        { signal }
      ),
    () => {
      void client.invalidateQueries({ queryKey: key })
    },
    { refresh: false }
  )
  const rows = useQuery({
    queryKey: [
      ...key,
      'items',
      selected?.store_id,
      selected?.id,
      urgent,
      parameters,
      page
    ],
    queryFn: ({ signal }) =>
      inventoryReplenishment(
        scope.workspace!.id,
        {
          ...parameters,
          store_id: selected!.store_id,
          destination_id: selected!.id,
          urgent_only: urgent,
          limit: 20,
          offset: page * 20
        },
        { signal }
      ),
    enabled: !!selected,
    refetchInterval: query => reportInterval(query.state.data)
  })
  return { list, rows, refresh }
}
