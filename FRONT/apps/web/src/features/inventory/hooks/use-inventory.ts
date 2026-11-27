'use client'

import { reportInterval } from '@app/analytics/polling'
import { useQuery } from '@tanstack/react-query'

import { useAuth } from '@/features/auth/auth-provider'
import { useCoverageChannel } from '@/features/inventory/hooks/use-coverage-channel'
import { useWorkspace } from '@/features/workspace/workspace-provider'

import { useDebouncedValue } from '@/hooks/use-debounced-value'

import { stockQuery } from '@/lib/report-queries'

export const stockPageSize = 20
export function inventoryPoll(data?: {
  is_loading?: boolean
  turnover_loading?: boolean
}) {
  return reportInterval({
    is_loading: data?.is_loading || data?.turnover_loading
  })
}
export function useInventory(
  search: string,
  inStock: boolean,
  page: number,
  showItems: boolean
) {
  const scope = useWorkspace()
  const [coverage_channel] = useCoverageChannel()
  const { user } = useAuth()
  const debounced = useDebouncedValue(search.trim())
  const key = [
    'user',
    user?.id,
    scope.workspace?.id,
    'inventory',
    scope.accessKey,
    coverage_channel
  ]
  const supported = scope.selected.some(store =>
    store.features.includes('inventory')
  )
  const enabled =
    scope.ready && !!scope.workspace && supported && scope.can('inventory.read')
  const source = {
    userId: user?.id,
    workspaceId: scope.workspace?.id,
    accessKey: scope.accessKey,
    storeId: scope.store?.id,
    canStock: scope.can('inventory.read')
  }
  const summary = useQuery({
    ...stockQuery(source, coverage_channel),
    enabled,
    refetchInterval: query => inventoryPoll(query.state.data)
  })
  const items = useQuery({
    ...stockQuery(source, coverage_channel, {
      search: debounced,
      inStock,
      page
    }),
    enabled: enabled && showItems,
    refetchInterval: query => inventoryPoll(query.state.data)
  })
  return {
    key,
    summary,
    items,
    supported,
    searching: debounced !== search.trim(),
    fetching: summary.isFetching || (showItems && items.isFetching)
  }
}
