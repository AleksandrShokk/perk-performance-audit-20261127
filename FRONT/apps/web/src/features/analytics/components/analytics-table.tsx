'use client'

import { formatNumber, formatPercent, formatUnits } from '@app/analytics/format'
import { ArrowDown, ArrowUp, Search, X } from 'lucide-react'
import { useState } from 'react'

import { Empty } from '@/components/feedback'
import { ProductLabel } from '@/components/product-label'
import { TablePagination } from '@/components/table-pagination'
import { Input } from '@/components/ui/input'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

import { useAuth } from '@/features/auth/auth-provider'
import { ReportHint } from '@/features/finance/components/report-hint'
import { financeMoney } from '@/features/finance/model/finance-format'
import type { Metric } from '@/features/overview/chart-data'
import {
  type IdentifierMode,
  identifierModes,
  platformName
} from '@/features/products/model/catalog'

import { useDebouncedValue } from '@/hooks/use-debounced-value'

import { usePreference } from '@/lib/preferences'

import type { Analytics } from '../hooks/use-analytics'
import {
  type AnalyticsRow,
  type AnalyticsSort,
  analyticsArticle,
  analyticsTitle,
  productChange,
  selectAnalyticsRows
} from '../model/products'

export function AnalyticsTable({
  analytics,
  unit,
  comparison,
  onOpen
}: {
  analytics: Analytics
  unit: 'amount' | 'units'
  comparison: boolean
  onOpen: (row: AnalyticsRow) => void
}) {
  const { user } = useAuth()
  const [view, setView] = useState<'sales' | 'funnel'>('sales')
  const [search, setSearch] = useState('')
  const debounced = useDebouncedValue(search)
  const [store, setStore] = useState('')
  const [sort, setSort] = useState<AnalyticsSort>('orders')
  const [descending, setDescending] = useState(true)
  const [page, setPage] = useState(0)
  const [pageSize, setPageSize] = useState(25)
  const [savedMode, setSavedMode] = usePreference(
    `perk.web.products.identifier.${user?.id}`
  )
  const mode: IdentifierMode =
    savedMode === 'barcode' || savedMode === 'marketplace'
      ? savedMode
      : 'vendor'
  const rows = selectAnalyticsRows(
    analytics.products,
    debounced,
    store,
    sort,
    descending,
    view === 'funnel' ? 'units' : unit
  )
  const partialPrices = analytics.products.some(
    row => row.current.partial_amounts?.length
  )
  const currentPage = Math.min(
    page,
    Math.max(0, Math.ceil(rows.length / pageSize) - 1)
  )
  const sortColumn = (field: AnalyticsSort) => {
    setSort(field)
    setDescending(field === sort ? !descending : true)
    setPage(0)
  }
  const heading = (field: AnalyticsSort, label: string) => (
    <th
      aria-sort={
        field === sort ? (descending ? 'descending' : 'ascending') : 'none'
      }
    >
      <button
        onClick={() => sortColumn(field)}
        aria-label={`Сортировать: ${label}`}
      >
        {label}
        {field === sort &&
          (descending ? <ArrowDown size={12} /> : <ArrowUp size={12} />)}
      </button>
    </th>
  )
  return (
    <Tabs
      asChild
      value={view}
      onValueChange={value => {
        setView(value as typeof view)
        setPage(0)
      }}
    >
      <section
        className='surface analytics-products'
        aria-label='Аналитика по товарам'
      >
        <div className='section-heading'>
          <div className='catalog-title'>
            <h2>{analytics.truncated ? 'Топ товаров' : 'Товары'}</h2>
            {(analytics.truncated || partialPrices) && (
              <ReportHint label='О списке товаров'>
                {analytics.truncated &&
                  'В списке первые 500 позиций каждого кабинета по числу заказов. Поиск и сортировка применяются к этому списку. Общая сводка охватывает весь период.'}
                {partialPrices &&
                  ' При неполных ценах показана известная сумма, изменение суммы не рассчитывается.'}
              </ReportHint>
            )}
          </div>
          <TabsList aria-label='Таблица аналитики'>
            <TabsTrigger value='sales'>Продажи</TabsTrigger>
            <TabsTrigger value='funnel'>Воронка</TabsTrigger>
          </TabsList>
        </div>
        <div className='catalog-toolbar analytics-table-toolbar'>
          <div className='catalog-search'>
            <Search size={16} />
            <Input
              maxLength={100}
              placeholder='Название, артикул или штрихкод'
              aria-label='Поиск в аналитике товаров'
              value={search}
              onChange={event => {
                setSearch(event.target.value)
                setPage(0)
              }}
            />
            {search && (
              <button
                aria-label='Очистить поиск'
                onClick={() => {
                  setSearch('')
                  setPage(0)
                }}
              >
                <X size={15} />
              </button>
            )}
          </div>
          {analytics.stores.length > 1 && (
            <select
              className='native-select'
              aria-label='Кабинет в таблице аналитики'
              value={store}
              onChange={event => {
                setStore(event.target.value)
                setPage(0)
              }}
            >
              <option value=''>Все кабинеты</option>
              {analytics.stores.map(store => (
                <option
                  key={store.id}
                  value={store.id}
                >
                  {store.name} · {platformName(store.marketplace)}
                </option>
              ))}
            </select>
          )}
          <select
            className='native-select catalog-identifier'
            aria-label='Отображение артикула'
            value={mode}
            onChange={event => setSavedMode(event.target.value)}
          >
            {identifierModes.map(([key, label]) => (
              <option
                key={key}
                value={key}
              >
                {label}
              </option>
            ))}
          </select>
        </div>
        <TabsContent value={view}>
          {rows.length ? (
            <>
              <div className='analytics-table-scroll'>
                <table className='analytics-data'>
                  <thead>
                    <tr>
                      <th>Товар</th>
                      <th className='analytics-store'>Кабинет</th>
                      {view === 'sales' ? (
                        <>
                          {heading('orders', 'Заказано')}
                          {heading('buyouts', 'Выкуплено')}
                          {heading('cancellations', 'Отмены и возвраты')}
                          {heading('buyout_percent', 'Доля выкупа')}
                        </>
                      ) : (
                        <>
                          {heading('opens', 'Просмотры')}
                          {heading('carts', 'В корзину')}
                          {heading('orders', 'Заказано')}
                          <th>В корзину, %</th>
                          <th>В заказ, %</th>
                        </>
                      )}
                    </tr>
                  </thead>
                  <tbody>
                    {rows
                      .slice(
                        currentPage * pageSize,
                        (currentPage + 1) * pageSize
                      )
                      .map(row => (
                        <tr key={row.key}>
                          <td>
                            <button
                              className='analytics-product-button'
                              aria-label={`Аналитика ${analyticsTitle(row)} · ${row.current.vendor_code || row.key}`}
                              onClick={() => onOpen(row)}
                            >
                              <ProductLabel
                                title={analyticsTitle(row)}
                                article={analyticsArticle(row, mode)}
                                photo={row.current.photos?.[0]}
                              />
                              <small className='analytics-mobile-store'>
                                {row.storeName} ·{' '}
                                {platformName(row.marketplace)}
                              </small>
                            </button>
                          </td>
                          <td className='analytics-store'>
                            {row.storeName}
                            <small>{platformName(row.marketplace)}</small>
                          </td>
                          {view === 'sales' ? (
                            <>
                              {(
                                [
                                  'orders',
                                  'buyouts',
                                  'cancellations'
                                ] as Metric[]
                              ).map(metric => (
                                <td
                                  key={metric}
                                  className='analytics-numeric'
                                >
                                  <strong>
                                    {unit === 'amount'
                                      ? row.currency
                                        ? financeMoney(
                                            row.current[`${metric}_amount`],
                                            row.currency
                                          )
                                        : '—'
                                      : formatUnits(row.current[metric])}
                                  </strong>
                                  {unit === 'amount' && (
                                    <small>
                                      {formatUnits(row.current[metric])}
                                    </small>
                                  )}
                                  {comparison && (
                                    <small className='analytics-change'>
                                      {formatPercent(
                                        productChange(row, metric, unit),
                                        { signed: true }
                                      )}
                                    </small>
                                  )}
                                </td>
                              ))}
                              <td className='analytics-numeric'>
                                {formatPercent(
                                  row.complete
                                    ? row.current.buyout_percent
                                    : null
                                )}
                              </td>
                            </>
                          ) : (
                            <>
                              <td className='analytics-numeric'>
                                {formatNumber(row.current.opens)}
                              </td>
                              <td className='analytics-numeric'>
                                {formatNumber(row.current.carts)}
                              </td>
                              <td className='analytics-numeric'>
                                {formatNumber(row.current.orders)}
                              </td>
                              <td className='analytics-numeric'>
                                {formatPercent(
                                  row.complete
                                    ? row.current.add_to_cart_percent
                                    : null
                                )}
                              </td>
                              <td className='analytics-numeric'>
                                {formatPercent(
                                  row.complete
                                    ? row.current.cart_to_order_percent
                                    : null
                                )}
                              </td>
                            </>
                          )}
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
              <div className='table-footer'>
                <span>
                  {currentPage * pageSize + 1}–
                  {Math.min((currentPage + 1) * pageSize, rows.length)} из{' '}
                  {formatNumber(rows.length)}
                </span>
                <TablePagination
                  label='аналитики'
                  page={currentPage}
                  pageSize={pageSize}
                  total={rows.length}
                  onPage={setPage}
                  onPageSize={size => {
                    setPageSize(size)
                    setPage(0)
                  }}
                />
              </div>
            </>
          ) : (
            <Empty
              title={
                search || store
                  ? 'Товары не найдены'
                  : 'Статистики по товарам пока нет'
              }
            />
          )}
        </TabsContent>
      </section>
    </Tabs>
  )
}
