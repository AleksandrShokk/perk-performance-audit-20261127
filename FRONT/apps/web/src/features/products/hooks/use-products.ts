'use client'

import { reportInterval } from '@app/analytics/polling'
import { useQuery } from '@tanstack/react-query'

import { useAuth } from '@/features/auth/auth-provider'
import { useWorkspace } from '@/features/workspace/workspace-provider'

import { useDebouncedValue } from '@/hooks/use-debounced-value'

import { productQuery } from '@/lib/report-queries'

export const catalogPageSize = 25
export function useProducts(
  search: string,
  inStock: boolean,
  missingCost: boolean,
  page: number,
  pageSize = catalogPageSize,
  combineMarketplaces = false
) {
  const scope = useWorkspace()
  const { user } = useAuth()
  const debounced = useDebouncedValue(search.trim())
  const query = useQuery({
    ...productQuery(
      {
        userId: user?.id,
        workspaceId: scope.workspace?.id,
        accessKey: scope.accessKey,
        storeId: scope.store?.id,
        canStock: scope.can('inventory.read')
      },
      {
        search: debounced,
        inStock,
        missingCost: scope.can('profit.read') && missingCost,
        page,
        pageSize,
        combined: combineMarketplaces
      }
    ),
    enabled:
      scope.ready &&
      !!scope.workspace &&
      scope.selected.some(store => store.features.includes('catalog')) &&
      (scope.can('inventory.read') || scope.can('profit.read')),
    refetchInterval: query => reportInterval(query.state.data)
  })
  return { ...query, searching: debounced !== search.trim() }
}
