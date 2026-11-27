'use client'

import { useInfiniteQuery } from '@tanstack/react-query'
import { useState } from 'react'

import {
  type ProductItem,
  type ProductVariant,
  costsList,
  variantCostsList
} from '@app/api'

import { Empty, ErrorNotice, Loading } from '@/components/feedback'
import { Button } from '@/components/ui/button'

import { useAuth } from '@/features/auth/auth-provider'
import { useWorkspace } from '@/features/workspace/workspace-provider'

import { exactCost } from '../model/catalog'

import { CostEditor } from './cost-editor'

export function VariantCosts({
  product,
  variant,
  workspaceId,
  marketplace,
  currency,
  onSaved
}: {
  product: ProductItem
  variant?: ProductVariant
  workspaceId: string
  marketplace: string
  currency: string
  onSaved: () => void
}) {
  const scope = useWorkspace()
  const { user } = useAuth()
  const [editing, setEditing] = useState(false)
  const [historyOpen, setHistoryOpen] = useState(false)
  const isOzon = marketplace === 'ozon'
  const supported = isOzon ? !!variant?.id : !!product.nm_id
  const history = useInfiniteQuery({
    queryKey: [
      'user',
      user?.id,
      workspaceId,
      'catalog-cost-history',
      scope.accessKey,
      product.store_id,
      product.id || product.nm_id,
      isOzon ? variant?.id : 'all-sizes'
    ],
    initialPageParam: 0,
    queryFn: async ({
      pageParam,
      signal
    }): Promise<
      {
        amount: string
        currency: string
        effective_from: string
        barcode?: string
      }[]
    > => {
      if (isOzon)
        return (
          await variantCostsList(
            workspaceId,
            product.store_id,
            { variant_id: variant!.id, limit: 50, offset: pageParam },
            { signal }
          )
        ).map(row => ({ ...row, barcode: '' }))
      return costsList(
        workspaceId,
        product.store_id,
        { nm_id: product.nm_id, limit: 50, offset: pageParam },
        { signal }
      )
    },
    getNextPageParam: (last, _pages, offset) =>
      last.length === 50 && offset < 50000 ? offset + 50 : undefined,
    enabled: supported && historyOpen && scope.can('profit.read')
  })
  const prices = (history.data?.pages.flat() ?? [])
    .filter(row => !row.barcode || variant?.barcodes.includes(row.barcode))
    .sort((a, b) => b.effective_from.localeCompare(a.effective_from))
  return (
    <section className='variant-costs'>
      {editing ? (
        <CostEditor
          product={product}
          variant={variant}
          workspaceId={workspaceId}
          marketplace={marketplace}
          currency={currency}
          onSaved={() => {
            setEditing(false)
            void history.refetch()
            onSaved()
          }}
          onCancel={() => setEditing(false)}
        />
      ) : (
        <div className='variant-cost-current'>
          <div>
            <span>Себестоимость</span>
            <strong>{exactCost(variant?.unit_cost ?? null, currency)}</strong>
          </div>
          {scope.can('costs.write') && (
            <Button
              variant='secondary'
              disabled={!supported}
              onClick={() => setEditing(true)}
            >
              Изменить
            </Button>
          )}
        </div>
      )}
      <details
        className='cost-history'
        onToggle={event => setHistoryOpen(event.currentTarget.open)}
      >
        <summary>История себестоимости</summary>
        <ErrorNotice
          error={history.error}
          onRetry={() => void history.refetch()}
        />
        {!supported ? (
          <Empty title='История пока недоступна' />
        ) : history.isPending ? (
          <Loading label='Загружаем историю' />
        ) : !prices.length && !history.error ? (
          <Empty title='Себестоимость ещё не задана' />
        ) : (
          <div className='cost-history-list'>
            {prices.map((row, index) => (
              <div
                key={`${row.effective_from}:${row.barcode}:${row.currency}:${index}`}
              >
                <span>
                  {new Intl.DateTimeFormat('ru-RU').format(
                    new Date(`${row.effective_from}T12:00:00`)
                  )}
                  <small>
                    {isOzon ? 'Этот вариант' : row.barcode || 'Все размеры'}
                  </small>
                </span>
                <strong>{exactCost(row.amount, row.currency)}</strong>
              </div>
            ))}
          </div>
        )}
        {history.hasNextPage && (
          <Button
            variant='ghost'
            disabled={history.isFetchingNextPage}
            onClick={() => void history.fetchNextPage()}
          >
            Показать ещё
          </Button>
        )}
      </details>
    </section>
  )
}
