'use client'

import { formatUnits } from '@app/analytics/format'
import { useQueries } from '@tanstack/react-query'

import { type InventoryOverview, inventoryOverview } from '@app/api'

import { Empty, ErrorNotice } from '@/components/feedback'
import { Skeleton } from '@/components/ui/skeleton'

import { financeMoney } from '@/features/finance/model/finance-format'
import { useCoverageChannel } from '@/features/inventory/hooks/use-coverage-channel'
import { platformName } from '@/features/products/model/catalog'
import { useWorkspace } from '@/features/workspace/workspace-provider'

import { inventoryPoll } from '../hooks/use-inventory'
import { stockCover } from '../model/stock'

import type { StockPriceMode } from './stock-table'

export function CabinetStocks({
  queryKey,
  priceMode
}: {
  queryKey: unknown[]
  priceMode: StockPriceMode
}) {
  const scope = useWorkspace()
  const [coverage_channel] = useCoverageChannel()
  const stores = scope.selected.filter(store =>
    store.features.includes('inventory')
  )
  const queries = useQueries({
    queries: stores.map(store => ({
      queryKey: [...queryKey, 'summary', store.id, coverage_channel],
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        inventoryOverview(
          scope.workspace!.id,
          { coverage_channel, store_id: store.id, limit: 0 },
          { signal }
        ),
      enabled: scope.ready && !!scope.workspace && scope.can('inventory.read'),
      refetchInterval: (query: { state: { data?: InventoryOverview } }) =>
        inventoryPoll(query.state.data)
    }))
  })
  return (
    <section
      className='surface stock-table'
      aria-label='Остатки по кабинетам'
    >
      <div className='stock-table-scroll'>
        <table className='stock-data'>
          <thead>
            <tr>
              <th>Кабинет</th>
              <th>FBO</th>
              <th>FBS</th>
              <th>Запас, дней</th>
            </tr>
          </thead>
          <tbody>
            {stores.map((store, index) => {
              const query = queries[index]
              const data = query.data
              const mode =
                scope.can('profit.read') && data?.can_cost
                  ? priceMode
                  : 'retail'
              return (
                <tr key={store.id}>
                  <td>
                    <button
                      className='stock-store-button'
                      onClick={() => scope.selectStore(store.id)}
                    >
                      {store.name}
                      <small>{platformName(store.marketplace)}</small>
                    </button>
                    {query.error && (
                      <ErrorNotice
                        error={query.error}
                        onRetry={() => void query.refetch()}
                      />
                    )}
                  </td>
                  {(['fbo', 'fbs'] as const).map(channel => (
                    <td
                      className='stock-channel-cell'
                      key={channel}
                    >
                      {query.isPending ? (
                        <Skeleton className='h-8 w-24' />
                      ) : (
                        <>
                          <strong>{formatUnits(data?.[channel].units)}</strong>
                          <small>
                            {financeMoney(
                              mode === 'cost'
                                ? data?.[channel].cost_value
                                : data?.[channel].retail_value,
                              data?.currency
                            )}
                          </small>
                        </>
                      )}
                    </td>
                  ))}
                  <td className='stock-cover-cell'>
                    {query.isPending
                      ? '—'
                      : data?.turnover_supported === false
                        ? '—'
                        : stockCover(
                            data?.turnover_days,
                            data?.turnover_loading ? 'loading' : undefined
                          )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {!stores.length && <Empty title='Нет доступных кабинетов' />}
    </section>
  )
}
