'use client'

import { LoaderCircle, RefreshCw, Search, Settings2, X } from 'lucide-react'
import { useState } from 'react'

import type { InventoryPosition } from '@app/api'

import { AppShell } from '@/components/app-shell'
import { Empty, ErrorNotice, Loading } from '@/components/feedback'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'

import { useAuth } from '@/features/auth/auth-provider'
import { RequireAuth } from '@/features/auth/require-auth'
import { ReportHint } from '@/features/finance/components/report-hint'
import {
  type IdentifierMode,
  identifierModes
} from '@/features/products/model/catalog'
import { ConnectStore } from '@/features/workspace/connect-store'
import { useWorkspace } from '@/features/workspace/workspace-provider'

import { useRefreshWorkspace } from '@/hooks/use-refresh-workspace'

import { usePreference } from '@/lib/preferences'

import { CabinetStocks } from './components/cabinet-stocks'
import { CoverageControl } from './components/coverage-control'
import { FbsSettings } from './components/fbs-settings'
import { InventoryExport } from './components/inventory-export'
import { StockDetails } from './components/stock-details'
import { StockSummary } from './components/stock-summary'
import { type StockPriceMode, StockTable } from './components/stock-table'
import { useInventory } from './hooks/use-inventory'
import { positionKey } from './model/stock'

export function InventoryPage() {
  const { user } = useAuth()
  const scope = useWorkspace()
  return (
    <RequireAuth>
      <Inventory
        key={`${user?.id}:${scope.accessKey}:${scope.store?.id ?? 'all'}`}
      />
    </RequireAuth>
  )
}
function Inventory() {
  const scope = useWorkspace()
  const { user } = useAuth()
  const [search, setSearch] = useState('')
  const [inStock, setInStock] = useState(true)
  const [page, setPage] = useState(0)
  const [tab, setTab] = useState<'products' | 'cabinets'>('products')
  const [selection, setSelection] = useState<InventoryPosition | null>(null)
  const [settings, setSettings] = useState<string | null>(null)
  const [priceMode, setPriceMode] = useState<StockPriceMode>('retail')
  const [savedMode, setSavedMode] = usePreference(
    `perk.web.products.identifier.${user?.id}`
  )
  const mode: IdentifierMode =
    savedMode === 'marketplace' || savedMode === 'barcode'
      ? savedMode
      : 'vendor'
  const query = useInventory(search, inStock, page, tab === 'products')
  const refresh = useRefreshWorkspace()
  const summary = query.summary.data
  const items = query.items.data
  const canRead = scope.can('inventory.read')
  const canCost = scope.can('profit.read') && !!summary?.can_cost
  const canCabinets =
    scope.selected.filter(store => store.features.includes('inventory'))
      .length > 1
  const canSettings =
    scope.admin &&
    canCabinets &&
    scope.selected.some(store => store.marketplace === 'ozon')
  const selected =
    selection &&
    (items?.items.find(
      position => positionKey(position) === positionKey(selection)
    ) ??
      selection)
  const stockError =
    summary?.error_code || items?.error_code
      ? new Error(
          'Не удалось обновить остатки. Проверьте доступ к складам в кабинете.'
        )
      : null
  const reset = () => {
    setSearch('')
    setInStock(true)
    setPage(0)
  }
  return (
    <AppShell>
      <div className='page-heading'>
        <div className='catalog-title'>
          <h1>Остатки</h1>
          <CoverageControl />
          <ReportHint label='Об оценке остатков'>
            Стоимость — по текущей цене продавца после его скидки, без скидки
            маркетплейса.
          </ReportHint>
          {summary?.is_loading && (
            <LoaderCircle
              size={15}
              className='animate-spin text-primary'
              aria-label='Остатки загружаются'
            />
          )}
        </div>
        <div className='catalog-heading-actions'>
          {canRead && <InventoryExport disabled={scope.loading || !summary} />}
          {canSettings && (
            <Button
              variant='outline'
              onClick={() => setSettings(crypto.randomUUID())}
            >
              <Settings2 size={15} />
              Учёт FBS
            </Button>
          )}
          <Button
            variant='ghost'
            className='refresh-button'
            aria-label='Обновить остатки'
            disabled={scope.loading || query.fetching || !canRead}
            onClick={() => void Promise.all([scope.refresh(), refresh()])}
          >
            <RefreshCw size={15} />
            <span>Обновить</span>
          </Button>
        </div>
      </div>
      <ErrorNotice
        error={scope.error}
        onRetry={() => void scope.refresh()}
      />
      {scope.loading ? (
        <Loading />
      ) : !canRead ? (
        <Empty title='Нет доступа к остаткам' />
      ) : !scope.stores.length ? (
        <section className='surface welcome-card'>
          <h2>Подключите магазин</h2>
          <ConnectStore />
        </section>
      ) : !query.supported ? (
        <Empty title='Остатки пока недоступны' />
      ) : (
        <>
          <ErrorNotice
            error={query.summary.error ?? stockError}
            onRetry={() => void refresh()}
          />
          <StockSummary
            data={summary}
            pending={query.summary.isPending}
            canCost={canCost}
            canCabinets={canCabinets}
            onCabinets={() => setTab('cabinets')}
          />
          <div className='stock-toolbar'>
            <div
              className='stock-switch'
              role='tablist'
              aria-label='Отображение остатков'
            >
              {(
                [
                  'products',
                  ...(canCabinets ? (['cabinets'] as const) : [])
                ] as const
              ).map(value => (
                <button
                  role='tab'
                  key={value}
                  id={`stock-${value}-tab`}
                  aria-selected={tab === value}
                  aria-controls='stock-list-panel'
                  tabIndex={tab === value ? 0 : -1}
                  onClick={() => setTab(value)}
                  onKeyDown={event => {
                    if (
                      canCabinets &&
                      (event.key === 'ArrowLeft' || event.key === 'ArrowRight')
                    ) {
                      event.preventDefault()
                      const next =
                        value === 'products' ? 'cabinets' : 'products'
                      setTab(next)
                      document.getElementById(`stock-${next}-tab`)?.focus()
                    }
                  }}
                >
                  {value === 'products' ? 'По товарам' : 'По кабинетам'}
                </button>
              ))}
            </div>
            {canCost && tab === 'cabinets' && (
              <select
                className='native-select'
                aria-label='Оценка остатков'
                value={priceMode}
                onChange={event =>
                  setPriceMode(event.target.value as StockPriceMode)
                }
              >
                <option value='retail'>По цене продавца</option>
                <option value='cost'>По себестоимости</option>
              </select>
            )}
          </div>
          <div
            role='tabpanel'
            id='stock-list-panel'
            aria-labelledby={`stock-${tab}-tab`}
          >
            {tab === 'cabinets' ? (
              <CabinetStocks
                queryKey={query.key}
                priceMode={canCost ? priceMode : 'retail'}
              />
            ) : (
              <>
                <div className='catalog-toolbar stock-filters'>
                  <div className='catalog-search'>
                    <Search size={17} />
                    <Input
                      aria-label='Поиск остатков'
                      placeholder='Название, артикул или штрихкод'
                      value={search}
                      maxLength={100}
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
                    <button
                      aria-pressed={inStock}
                      onClick={() => {
                        setInStock(!inStock)
                        setPage(0)
                      }}
                    >
                      В наличии
                    </button>
                  </div>
                  <div className='stock-display-controls'>
                    {canCost && (
                      <select
                        className='native-select'
                        aria-label='Оценка остатков'
                        value={priceMode}
                        onChange={event =>
                          setPriceMode(event.target.value as StockPriceMode)
                        }
                      >
                        <option value='retail'>По цене продавца</option>
                        <option value='cost'>По себестоимости</option>
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
                  {query.searching && (
                    <LoaderCircle
                      className='animate-spin text-primary'
                      size={15}
                      aria-label='Ищем остатки'
                    />
                  )}
                </div>
                <ErrorNotice
                  error={query.items.error}
                  onRetry={() => void query.items.refetch()}
                />
                {query.items.isPending ? (
                  <Skeleton className='h-96 w-full rounded-2xl' />
                ) : items?.items.length ? (
                  <StockTable
                    data={items}
                    mode={mode}
                    priceMode={canCost && items.can_cost ? priceMode : 'retail'}
                    busy={query.items.isFetching || query.searching}
                    onPage={setPage}
                    onOpen={setSelection}
                  />
                ) : !query.items.error ? (
                  <section className='surface'>
                    <Empty
                      title={
                        items?.is_loading
                          ? 'Загружаем остатки'
                          : search
                            ? 'Товары не найдены'
                            : inStock
                              ? 'Нет товаров в наличии'
                              : 'Товаров пока нет'
                      }
                    >
                      {(search || inStock || page > 0) && (
                        <Button
                          variant='ghost'
                          onClick={() => {
                            reset()
                            setInStock(false)
                          }}
                        >
                          Показать все товары
                        </Button>
                      )}
                    </Empty>
                  </section>
                ) : null}
              </>
            )}
          </div>
        </>
      )}
      {selected && canRead && (
        <StockDetails
          key={positionKey(selected)}
          position={selected}
          currency={items?.currency ?? 'RUB'}
          canCost={canCost && !!items?.can_cost}
          onClose={() => setSelection(null)}
        />
      )}
      {settings && canSettings && (
        <FbsSettings
          key={settings}
          queryKey={query.key}
          onClose={() => setSettings(null)}
        />
      )}
    </AppShell>
  )
}
