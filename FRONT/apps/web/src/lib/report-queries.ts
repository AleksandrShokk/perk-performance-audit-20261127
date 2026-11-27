import type { DateRange } from '@app/analytics/dates'

import type { SupplyParameters } from '@app/schemas'

import {
  catalogModels,
  financeOverview,
  inventoryOverview,
  inventoryReplenishment
} from '@app/api'

export type ReportScope = {
  userId?: string
  workspaceId?: string
  accessKey: string
  storeId?: string
  canStock: boolean
}
const root = (s: ReportScope) => ['user', s.userId, s.workspaceId]

export function financeQuery(s: ReportScope, range: DateRange) {
  return {
    queryKey: [...root(s), 'finance', s.accessKey, s.storeId ?? 'all', range],
    queryFn: ({ signal }: { signal: AbortSignal }) =>
      financeOverview(
        s.workspaceId!,
        { ...range, store_id: s.storeId },
        { signal }
      )
  }
}
export function stockQuery(
  s: ReportScope,
  channel: 'fbo' | 'fbs' | 'all',
  table?: { search: string; inStock: boolean; page: number }
) {
  const key = [...root(s), 'inventory', s.accessKey, channel]
  return {
    queryKey: table
      ? [
          ...key,
          'items',
          s.storeId ?? 'all',
          table.search,
          table.inStock,
          table.page
        ]
      : [...key, 'summary', s.storeId ?? 'all'],
    queryFn: ({ signal }: { signal: AbortSignal }) =>
      inventoryOverview(
        s.workspaceId!,
        {
          coverage_channel: channel,
          store_id: s.storeId,
          ...(table
            ? {
                q: table.search,
                in_stock: table.inStock,
                limit: 20,
                offset: table.page * 20
              }
            : { limit: 0 })
        },
        { signal }
      )
  }
}
export function productQuery(
  s: ReportScope,
  args: {
    search: string
    inStock: boolean
    missingCost: boolean
    page: number
    pageSize: number
    combined: boolean
  }
) {
  return {
    queryKey: [
      ...root(s),
      'catalog-models',
      s.accessKey,
      s.storeId ?? 'all',
      args.search,
      args.inStock,
      args.missingCost,
      args.page,
      args.pageSize,
      args.combined
    ],
    queryFn: ({ signal }: { signal: AbortSignal }) =>
      catalogModels(
        s.workspaceId!,
        {
          store_id: s.storeId,
          combine_marketplaces: !s.storeId && args.combined,
          q: args.search,
          in_stock: s.canStock && args.inStock,
          missing_cost: args.missingCost,
          limit: args.pageSize,
          offset: args.page * args.pageSize
        },
        { signal }
      )
  }
}
export function supplyQuery(
  s: ReportScope,
  parameters: SupplyParameters,
  table?: { storeId?: string; urgent: boolean; page: number }
) {
  const key = [...root(s), 'supplies-page', s.accessKey]
  return {
    queryKey: table
      ? [
          ...key,
          'recommendations',
          table.storeId ?? 'all',
          table.urgent,
          table.page,
          parameters
        ]
      : [...key, 'summary', s.storeId ?? 'all', parameters],
    queryFn: ({ signal }: { signal: AbortSignal }) =>
      inventoryReplenishment(
        s.workspaceId!,
        {
          ...parameters,
          ...(table
            ? {
                store_id: table.storeId,
                urgent_only: table.urgent,
                limit: 20,
                offset: table.page * 20
              }
            : { store_id: s.storeId, limit: 0 })
        },
        { signal }
      )
  }
}
