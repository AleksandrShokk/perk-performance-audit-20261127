'use client'

import { moscowToday } from '@app/analytics/dates'
import { formatNumber } from '@app/analytics/format'
import { Check, LoaderCircle, RefreshCw, Search, Upload, X } from 'lucide-react'
import { useState } from 'react'

import { AppShell } from '@/components/app-shell'
import { ChoiceSelect } from '@/components/choice-select'
import { Empty, ErrorNotice, Loading } from '@/components/feedback'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'

import { useAuth } from '@/features/auth/auth-provider'
import { RequireAuth } from '@/features/auth/require-auth'
import {
  type ActionSession,
  FinanceActionDialog
} from '@/features/finance/components/finance-action-dialog'
import { ReportHint } from '@/features/finance/components/report-hint'
import { useRefreshFinance } from '@/features/finance/hooks/use-finance'
import { ConnectStore } from '@/features/workspace/connect-store'
import { useWorkspace } from '@/features/workspace/workspace-provider'

import { usePreference } from '@/lib/preferences'

import { CatalogImportDialog } from './components/catalog-import-dialog'
import { CatalogTable } from './components/catalog-table'
import { GroupingDialog } from './components/grouping-dialog'
import {
  ProductDetails,
  type ProductSelection
} from './components/product-details'
import { useProducts } from './hooks/use-products'
import {
  type CatalogRow,
  type IdentifierMode,
  catalogRows,
  identifierModes
} from './model/catalog'

export function ProductsPage() {
  const { user } = useAuth()
  const scope = useWorkspace()
  return (
    <RequireAuth>
      <Catalog
        key={`${user?.id}:${scope.accessKey}:${scope.store?.id ?? 'all'}`}
      />
    </RequireAuth>
  )
}
function Catalog() {
  const scope = useWorkspace()
  const { user } = useAuth()
  const [search, setSearch] = useState('')
  const [inStock, setInStock] = useState(false)
  const [missingCost, setMissingCost] = useState(false)
  const [page, setPage] = useState(0)
  const [pageSize, setPageSize] = useState(25)
  const [saved, setSaved] = useState(false)
  const [matching, setMatching] = useState(false)
  const [grouping, setGrouping] = useState<{
    model?: ProductSelection['model']
  } | null>(null)
  const [selection, setSelection] = useState<ProductSelection | null>(null)
  const [importing, setImporting] = useState<ActionSession | null>(null)
  const [variants, setVariants] = usePreference(
    `perk.web.products.variants.${user?.id}`
  )
  const [identifierMode, setIdentifierMode] = usePreference(
    `perk.web.products.identifier.${user?.id}`
  )
  const mode: IdentifierMode =
    identifierMode === 'marketplace' || identifierMode === 'barcode'
      ? identifierMode
      : 'vendor'
  const [combined, setCombined] = usePreference(
    `perk.web.products.combined.${user?.id}`
  )
  const crossMarketplace =
    !scope.store &&
    scope.selected.some(s => s.marketplace === 'wildberries') &&
    scope.selected.some(s => s.marketplace === 'ozon')
  const join = crossMarketplace && combined !== 'false' && variants !== 'true'
  const query = useProducts(search, inStock, missingCost, page, pageSize, join)
  const refresh = useRefreshFinance()
  const data = query.data
  const rows = catalogRows(data?.items ?? [], variants === 'true')
  const canRead = scope.can('inventory.read') || scope.can('profit.read')
  const supported = scope.selected.some(store =>
    store.features.includes('catalog')
  )
  const reset = () => {
    setSearch('')
    setInStock(false)
    setMissingCost(false)
    setPage(0)
  }
  const open = (row: CatalogRow) => {
    setSaved(false)
    setSelection({
      id: crypto.randomUUID(),
      model: row.model,
      initialProduct: row.initialProduct
    })
  }
  const model = selection
    ? (data?.items.find(
        model =>
          model.id === selection.model.id &&
          model.store_id === selection.model.store_id
      ) ?? selection.model)
    : null
  return (
    <AppShell>
      <div className='page-heading'>
        <div className='catalog-title'>
          <h1>Товары</h1>
          <ReportHint label='О карточках товаров'>
            Объединение задано маркетплейсом или пользователем. Остатки в
            каталоге — FBO.
          </ReportHint>
          {data?.is_loading && (
            <LoaderCircle
              className='animate-spin text-primary'
              size={15}
              aria-label='Каталог загружается'
            />
          )}
        </div>
        <div className='catalog-heading-actions'>
          {saved && (
            <span
              className='finance-saved'
              role='status'
            >
              <Check size={14} />
              Сохранено
            </span>
          )}
          <Button
            variant='ghost'
            className='refresh-button'
            aria-label='Обновить каталог'
            disabled={scope.loading || query.isFetching || !canRead}
            onClick={() => void Promise.all([scope.refresh(), query.refetch()])}
          >
            <RefreshCw size={15} />
            <span>Обновить</span>
          </Button>
          {scope.admin && (
            <>
              <Button
                variant='outline'
                onClick={() => setGrouping({})}
              >
                Объединить карточки
              </Button>
              <Button
                variant='outline'
                onClick={() => setMatching(true)}
              >
                WB ↔ Ozon
              </Button>
            </>
          )}
          {scope.can('costs.write') && (
            <Button
              variant='outline'
              onClick={() => {
                setSaved(false)
                setImporting({ kind: 'cost', id: crypto.randomUUID() })
              }}
            >
              <Upload size={15} />
              Импорт себестоимости
            </Button>
          )}
        </div>
      </div>
      <ErrorNotice
        error={scope.error}
        onRetry={() => void scope.refresh()}
      />
      {scope.loading ? (
        <Loading />
      ) : !canRead ? (
        <Empty title='Нет доступа к товарам' />
      ) : !scope.stores.length ? (
        <section className='surface welcome-card'>
          <h2>Подключите магазин</h2>
          <ConnectStore />
        </section>
      ) : !supported ? (
        <Empty title='Каталог пока недоступен' />
      ) : (
        <>
          <div className='surface catalog-overview'>
            <div className='catalog-statistics'>
              {[
                ['Карточки', data?.total],
                ['Артикулы', data?.total_products],
                ['Варианты', data?.total_variants]
              ].map(([label, value]) => (
                <div key={String(label)}>
                  <span>{label}</span>
                  <strong>
                    {formatNumber(typeof value === 'number' ? value : null)}
                  </strong>
                </div>
              ))}
            </div>
            {crossMarketplace && (
              <ChoiceSelect
                label='Объединение площадок'
                value={join ? 'combined' : 'separate'}
                onChange={value => {
                  setCombined(String(value === 'combined'))
                  if (value === 'combined') setVariants('false')
                  setPage(0)
                }}
                options={[
                  { value: 'combined', label: 'WB и Ozon вместе' },
                  { value: 'separate', label: 'WB и Ozon отдельно' }
                ]}
              />
            )}
            <label className='catalog-checkbox'>
              <input
                type='checkbox'
                checked={variants === 'true'}
                onChange={event => {
                  setVariants(String(event.target.checked))
                  if (event.target.checked) setCombined('false')
                }}
              />
              Все варианты в списке
            </label>
          </div>
          <div className='catalog-toolbar'>
            <div className='catalog-search'>
              <Search size={17} />
              <Input
                aria-label='Поиск товаров'
                placeholder='Название, артикул или штрихкод'
                maxLength={100}
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
            <div className='catalog-filter-buttons'>
              {scope.can('inventory.read') && (
                <button
                  aria-pressed={inStock}
                  onClick={() => {
                    setInStock(!inStock)
                    setPage(0)
                  }}
                >
                  В наличии
                </button>
              )}
              {scope.can('profit.read') && (
                <button
                  aria-pressed={missingCost}
                  onClick={() => {
                    setMissingCost(!missingCost)
                    setPage(0)
                  }}
                >
                  Без себестоимости
                </button>
              )}
            </div>
            <select
              className='native-select catalog-identifier'
              aria-label='Отображение артикула'
              value={mode}
              onChange={event => setIdentifierMode(event.target.value)}
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
            {query.searching && (
              <LoaderCircle
                size={15}
                className='animate-spin text-primary'
                aria-label='Ищем товары'
              />
            )}
          </div>
          <ErrorNotice
            error={
              query.error ??
              (data?.error_code
                ? new Error(
                    'Не удалось обновить каталог. Проверьте доступ к товарам в кабинете.'
                  )
                : null)
            }
            onRetry={() => void query.refetch()}
          />
          {query.isPending ? (
            <Skeleton className='h-96 w-full rounded-2xl' />
          ) : rows.length ? (
            <CatalogTable
              pageSize={pageSize}
              onPageSize={size => {
                setPageSize(size)
                setPage(0)
              }}
              rows={rows}
              mode={mode}
              currency={data!.currency}
              canStock={scope.can('inventory.read')}
              canCost={scope.can('profit.read')}
              total={data!.total}
              page={page}
              busy={query.isFetching || query.searching}
              onPage={setPage}
              onOpen={open}
            />
          ) : !query.error ? (
            <section className='surface'>
              <Empty
                title={
                  data?.is_loading
                    ? 'Загружаем каталог'
                    : search || inStock || missingCost
                      ? 'Товары не найдены'
                      : 'Товаров пока нет'
                }
              >
                {(search || inStock || missingCost || page > 0) && (
                  <Button
                    variant='ghost'
                    onClick={reset}
                  >
                    Сбросить фильтры
                  </Button>
                )}
              </Empty>
            </section>
          ) : null}
        </>
      )}
      {selection && model && canRead && (
        <ProductDetails
          key={selection.id}
          model={model}
          initialProduct={selection.initialProduct}
          onGrouping={
            model.combined
              ? undefined
              : () => {
                  setGrouping({ model })
                  setSelection(null)
                }
          }
          currency={data?.currency ?? 'RUB'}
          onClose={() => setSelection(null)}
          onSaved={() => {
            setSelection(current =>
              current?.id === selection.id ? null : current
            )
            setPage(0)
            setSaved(true)
          }}
        />
      )}
      {grouping && scope.admin && (
        <GroupingDialog
          model={grouping.model}
          onClose={() => setGrouping(null)}
          onSaved={() => {
            setPage(0)
            setSaved(true)
            void refresh()
          }}
        />
      )}
      {matching && scope.admin && (
        <CatalogImportDialog
          kind='matching'
          onClose={() => setMatching(false)}
          onSaved={() => {
            setPage(0)
            setSaved(true)
            void refresh()
          }}
        />
      )}
      {importing && scope.can('costs.write') && (
        <FinanceActionDialog
          key={importing.id}
          action={importing}
          onClose={() => setImporting(null)}
          onRefresh={refresh}
          date={moscowToday()}
          currency={data?.currency ?? 'RUB'}
          onSaved={async () => {
            await refresh()
            setImporting(current =>
              current?.id === importing.id ? null : current
            )
            setPage(0)
            setSaved(true)
          }}
        />
      )}
    </AppShell>
  )
}
