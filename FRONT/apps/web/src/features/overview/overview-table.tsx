'use client'

import { formatMoney, formatNumber } from '@app/analytics/format'
import { useQuery } from '@tanstack/react-query'
import { ArrowDown, ArrowUpRight, Info } from 'lucide-react'
import Link from 'next/link'
import { useState } from 'react'

import {
  catalogProducts,
  inventoryOverview,
  inventoryReplenishment,
  inventorySupplies
} from '@app/api'

import { Empty, ErrorNotice, Loading } from '@/components/feedback'
import { ProductLabel } from '@/components/product-label'
import { TablePagination } from '@/components/table-pagination'
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger
} from '@/components/ui/tooltip'

import { useAuth } from '@/features/auth/auth-provider'
import { useCoverageChannel } from '@/features/inventory/hooks/use-coverage-channel'
import { useWorkspace } from '@/features/workspace/workspace-provider'

import type { Overview } from './use-overview'

export type TableTab = 'products' | 'inventory' | 'supplies'
const labels = {
  products: 'Топ товаров',
  inventory: 'Остатки',
  supplies: 'Поставки'
}
const statuses: Record<string, string> = {
  draft: 'Черновик',
  planned: 'Запланирована',
  ready_to_ship: 'Готова к отгрузке',
  shipped: 'В пути',
  accepting: 'Приёмка',
  accepted: 'Принята',
  cancelled: 'Отменена',
  unknown: '—'
}

export function OverviewTable({
  overview,
  tab,
  onTab
}: {
  overview: Overview
  tab: TableTab
  onTab: (tab: TableTab) => void
}) {
  const scope = useWorkspace()

  const tabs = (['products', 'inventory', 'supplies'] as const).filter(item =>
    scope.can(item === 'products' ? 'analytics.read' : 'inventory.read')
  )
  return (
    <section
      className='surface overview-table'
      id='reports'
      aria-label='Отчёты по товарам'
    >
      <div className='table-heading'>
        <div
          className='table-tabs'
          role='tablist'
          aria-label='Отчёты'
        >
          {tabs.map(item => (
            <button
              role='tab'
              aria-selected={tab === item}
              aria-controls={`panel-${item}`}
              id={`tab-${item}`}
              tabIndex={tab === item ? 0 : -1}
              onKeyDown={event => {
                if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight')
                  return
                event.preventDefault()
                const next =
                  tabs[
                    (tabs.indexOf(item) +
                      (event.key === 'ArrowRight' ? 1 : tabs.length - 1)) %
                      tabs.length
                  ]!
                onTab(next)
                document.getElementById(`tab-${next}`)?.focus()
              }}
              onClick={() => onTab(item)}
              key={item}
            >
              {labels[item]}
            </button>
          ))}
        </div>
        <Link
          className='text-link table-route'
          href={`/${tab}`}
          aria-label={`Открыть раздел ${labels[tab]}`}
        >
          Открыть раздел
          <ArrowUpRight size={15} />
        </Link>
      </div>
      <div
        role='tabpanel'
        id={`panel-${tab}`}
        aria-labelledby={`tab-${tab}`}
      >
        <TableContent
          key={`${tab}:${scope.store?.id ?? 'all'}:${overview.range.date_from}:${overview.range.date_to}`}
          overview={overview}
          tab={tab}
        />
      </div>
    </section>
  )
}
function TableContent({
  overview,
  tab
}: {
  overview: Overview
  tab: TableTab
}) {
  const scope = useWorkspace()
  const [coverage_channel] = useCoverageChannel()
  const { user } = useAuth()
  const [page, setPage] = useState(0)
  const [limit, setLimit] = useState(25)
  const [formed, setFormed] = useState(false)
  const params = {
    coverage_channel,
    store_id: scope.store?.id,
    limit,
    offset: page * limit
  }
  const key = [
    'user',
    user?.id,
    scope.workspace?.id,
    scope.accessKey,
    coverage_channel,
    scope.store?.id ?? 'all',
    'overview-table'
  ]
  const inventory = useQuery({
    queryKey: [...key, 'inventory', page, limit],
    queryFn: ({ signal }) =>
      inventoryOverview(
        scope.workspace!.id,
        { ...params, coverage_channel, in_stock: true },
        { signal }
      ),
    enabled: tab === 'inventory' && (page > 0 || limit !== 10) && scope.ready
  })
  const rec = useQuery({
    queryKey: [...key, 'replenishment', page, limit],
    queryFn: ({ signal }) =>
      inventoryReplenishment(scope.workspace!.id, params, { signal }),
    enabled:
      tab === 'supplies' && !formed && (page > 0 || limit !== 10) && scope.ready
  })
  const supplies = useQuery({
    queryKey: [...key, 'supplies', page, limit],
    queryFn: ({ signal }) =>
      inventorySupplies(scope.workspace!.id, params, { signal }),
    enabled:
      tab === 'supplies' && formed && (page > 0 || limit !== 10) && scope.ready
  })
  const catalog = useQuery({
    queryKey: [...key, 'catalog', overview.range],
    queryFn: ({ signal }) =>
      catalogProducts(
        scope.workspace!.id,
        { store_id: scope.store?.id, limit: 100 },
        { signal }
      ),
    enabled:
      tab === 'products' &&
      scope.can('inventory.read') &&
      scope.ready &&
      overview.products.some(row => !row.title),
    staleTime: 60000
  })
  const stock = page || limit !== 10 ? inventory : overview.inventory
  const replenishment = page || limit !== 10 ? rec : overview.replenishment
  const formedSupplies = page || limit !== 10 ? supplies : overview.supplies
  const products = overview.products
  const count =
    tab === 'products'
      ? products.length
      : tab === 'inventory'
        ? (stock.data?.count ?? 0)
        : formed
          ? (formedSupplies.data?.count ?? 0)
          : (replenishment.data?.count ?? 0)
  const source =
    tab === 'inventory'
      ? stock
      : tab === 'supplies'
        ? formed
          ? formedSupplies
          : replenishment
        : null
  const pending = source ? source.isPending : overview.salesPending
  const error = source?.error
  const metadata = new Map(
    (catalog.data?.items ?? []).map(product => [
      `${product.store_id}:${product.marketplace_code || product.nm_id || product.external_id || product.id}`,
      product
    ])
  )
  return (
    <>
      {tab === 'inventory' && (
        <div
          className='inventory-summary'
          id='inventory'
        >
          {[
            ['FBO', overview.inventory.data?.fbo],
            ['FBS', overview.inventory.data?.fbs]
          ].map(([label, value]) => {
            const amount = typeof value === 'object' ? value : undefined
            return (
              <div key={String(label)}>
                <span>{String(label)}</span>
                <strong>
                  {formatNumber(amount?.units)} <small>шт.</small>
                </strong>
                <span>
                  {formatMoney(
                    amount?.retail_value,
                    overview.inventory.data?.currency
                  )}
                </span>
              </div>
            )
          })}
          <div>
            <span>Запас в днях</span>
            <strong>
              {formatNumber(overview.inventory.data?.turnover_days, 1)}
            </strong>
          </div>
          {overview.inventory.data?.can_cost && (
            <div>
              <span>
                По себестоимости
                <Tooltip>
                  <TooltipTrigger asChild>
                    <button
                      className='icon-hint'
                      aria-label='О сумме по себестоимости'
                    >
                      <Info size={13} />
                    </button>
                  </TooltipTrigger>
                  <TooltipContent>
                    {overview.inventory.data.total.cost_complete
                      ? 'Себестоимость указана для всех остатков.'
                      : 'Сумма только по товарам с указанной себестоимостью.'}
                  </TooltipContent>
                </Tooltip>
              </span>
              <strong>
                {formatMoney(
                  overview.inventory.data.total.cost_value,
                  overview.inventory.data.currency
                )}
              </strong>
            </div>
          )}
        </div>
      )}
      {tab === 'supplies' && (
        <div
          className='table-subhead'
          id='supplies'
        >
          <div className='small-tabs'>
            <button
              aria-pressed={!formed}
              onClick={() => {
                setFormed(false)
                setPage(0)
              }}
            >
              Рекомендации
            </button>
            <button
              aria-pressed={formed}
              onClick={() => {
                setFormed(true)
                setPage(0)
              }}
            >
              В работе
            </button>
          </div>
          <span className='muted'>
            План на {overview.replenishment.data?.target_days ?? 30} дней
          </span>
        </div>
      )}
      <ErrorNotice
        error={error}
        onRetry={source ? () => void source.refetch() : undefined}
      />
      {pending ? (
        <Loading />
      ) : !count ? (
        <Empty title='Пока нет данных' />
      ) : (
        <div className='table-scroll'>
          <table className='data-table'>
            {tab === 'products' ? (
              <>
                <thead>
                  <tr>
                    <th>Товар</th>
                    <th>Кабинет</th>
                    <th>
                      Заказано <ArrowDown size={12} />
                    </th>
                    <th>Выкуплено</th>
                    <th>Отмены и возвраты</th>
                  </tr>
                </thead>
                <tbody>
                  {products.slice(page * limit, (page + 1) * limit).map(row => {
                    const code =
                      row.marketplace_code || row.nm_id || row.id || ''
                    const product = metadata.get(`${row.storeId}:${code}`)
                    return (
                      <tr key={`${row.storeId}:${code}`}>
                        <td>
                          <ProductLabel
                            title={
                              row.title ||
                              product?.title ||
                              `${row.marketplace === 'ozon' ? 'Ozon' : 'WB'} · ${code}`
                            }
                            article={
                              row.vendor_code || product?.vendor_code || code
                            }
                            photo={row.photos?.[0] || product?.photos?.[0]}
                          />
                        </td>
                        <td className='muted'>{row.storeName}</td>
                        <td>
                          <strong>
                            {row.currency
                              ? formatMoney(row.orders_amount, row.currency)
                              : '—'}
                          </strong>
                          <small>{formatNumber(row.orders)} шт.</small>
                        </td>
                        <td>
                          <strong>
                            {row.currency
                              ? formatMoney(row.buyouts_amount, row.currency)
                              : '—'}
                          </strong>
                          <small>{formatNumber(row.buyouts)} шт.</small>
                        </td>
                        <td>
                          <strong>
                            {row.currency
                              ? formatMoney(
                                  row.cancellations_amount,
                                  row.currency
                                )
                              : '—'}
                          </strong>
                          <small>{formatNumber(row.cancellations)} шт.</small>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </>
            ) : tab === 'inventory' ? (
              <>
                <thead>
                  <tr>
                    <th>Товар</th>
                    <th>Кабинет</th>
                    <th>FBO</th>
                    <th>FBS</th>
                    <th>Запас, дней</th>
                  </tr>
                </thead>
                <tbody>
                  {stock.data?.items.map(row => (
                    <tr key={`${row.product.store_id}:${row.product.nm_id}`}>
                      <td>
                        <ProductLabel
                          title={row.product.title}
                          article={row.product.vendor_code}
                          photo={row.product.photos?.[0]}
                        />
                      </td>
                      <td className='muted'>{row.product.store_name}</td>
                      <td>
                        <strong>{formatNumber(row.fbo.units)} шт.</strong>
                        <small>
                          {formatMoney(
                            row.fbo.retail_value,
                            stock.data?.currency
                          )}
                        </small>
                      </td>
                      <td>
                        <strong>{formatNumber(row.fbs.units)} шт.</strong>
                        <small>
                          {formatMoney(
                            row.fbs.retail_value,
                            stock.data?.currency
                          )}
                        </small>
                      </td>
                      <td>
                        {row.turnover_status === 'no_orders'
                          ? 'Нет заказов'
                          : formatNumber(row.turnover_days, 1)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </>
            ) : formed ? (
              <>
                <thead>
                  <tr>
                    <th>Поставка</th>
                    <th>Кабинет</th>
                    <th>Склад</th>
                    <th>Дата</th>
                    <th>Количество</th>
                    <th>Статус</th>
                  </tr>
                </thead>
                <tbody>
                  {formedSupplies.data?.items.map(row => (
                    <tr key={`${row.store_id}:${row.external_id}`}>
                      <td>
                        <strong>{row.display_number ?? row.external_id}</strong>
                      </td>
                      <td>{row.store_name}</td>
                      <td>{row.destination || '—'}</td>
                      <td>
                        {row.planned_date
                          ? new Intl.DateTimeFormat('ru-RU').format(
                              new Date(row.planned_date)
                            )
                          : '—'}
                      </td>
                      <td>{formatNumber(row.quantity)} шт.</td>
                      <td>
                        <span className='status-pill'>
                          {statuses[row.status] ?? row.native_status ?? '—'}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </>
            ) : (
              <>
                <thead>
                  <tr>
                    <th>Товар</th>
                    <th>Кабинет</th>
                    <th>Остаток</th>
                    <th>Запас, дней</th>
                    <th>К поставке</th>
                  </tr>
                </thead>
                <tbody>
                  {replenishment.data?.items.map(row => (
                    <tr key={`${row.store_id}:${row.id ?? row.nm_id}`}>
                      <td>
                        <ProductLabel
                          title={row.title}
                          article={row.vendor_code}
                          photo={row.photo}
                        />
                      </td>
                      <td className='muted'>{row.store_name}</td>
                      <td>{formatNumber(row.stock)} шт.</td>
                      <td>{formatNumber(row.days_of_stock, 1)}</td>
                      <td className='primary-number'>
                        {formatNumber(row.quantity)} шт.
                      </td>
                    </tr>
                  ))}
                </tbody>
              </>
            )}
          </table>
        </div>
      )}
      <div className='table-footer'>
        <span>
          {count
            ? `${page * limit + 1}–${Math.min((page + 1) * limit, count)} из ${formatNumber(count)}`
            : '0 позиций'}
        </span>
        {tab === 'products' && overview.productsTruncated && (
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                className='icon-hint'
                aria-label='О составе списка товаров'
              >
                <Info size={14} />
              </button>
            </TooltipTrigger>
            <TooltipContent>
              В отчёте получена только часть товаров.
            </TooltipContent>
          </Tooltip>
        )}
        <TablePagination
          page={page}
          pageSize={limit}
          total={count}
          busy={pending}
          onPage={setPage}
          onPageSize={size => {
            setLimit(size)
            setPage(0)
          }}
        />
      </div>
    </>
  )
}
