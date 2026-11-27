'use client'

import { LoaderCircle, RefreshCw } from 'lucide-react'
import { useState } from 'react'

import type { ReplenishmentItem, SupplyCard } from '@app/api'

import { AppShell } from '@/components/app-shell'
import { Empty, ErrorNotice, Loading } from '@/components/feedback'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

import { useAuth } from '@/features/auth/auth-provider'
import { RequireAuth } from '@/features/auth/require-auth'
import { CatalogImportDialog } from '@/features/products/components/catalog-import-dialog'
import {
  type IdentifierMode,
  identifierModes,
  platformName
} from '@/features/products/model/catalog'
import { ConnectStore } from '@/features/workspace/connect-store'
import { useWorkspace } from '@/features/workspace/workspace-provider'

import { useRefreshWorkspace } from '@/hooks/use-refresh-workspace'

import { usePreference } from '@/lib/preferences'

import { CreatePlanDialog } from './components/create-plan-dialog'
import { DestinationPanel } from './components/destination-panel'
import { PackagingDialog } from './components/packaging-dialog'
import { PlanEditor } from './components/plan-editor'
import { PlansTable } from './components/plan-list'
import { SupplyControls } from './components/supply-controls'
import {
  PlacedSupplyDetails,
  RecommendationDetails
} from './components/supply-details'
import { SupplySummary } from './components/supply-summary'
import {
  PlacedSuppliesTable,
  RecommendationsTable
} from './components/supply-tables'
import { usePlans } from './hooks/use-plans'
import { type SupplyView, useSupplies } from './hooks/use-supplies'
import { readSupplyParameters } from './model/parameters'
import { recommendationKey, supplyKey } from './model/supplies'

export function SuppliesPage() {
  const { user } = useAuth()
  const scope = useWorkspace()
  return (
    <RequireAuth>
      <Supplies
        key={`${user?.id}:${scope.accessKey}:${scope.store?.id ?? 'all'}`}
      />
    </RequireAuth>
  )
}
function Supplies() {
  const scope = useWorkspace()
  const { user } = useAuth()
  const [savedParameters, setParameters] = usePreference(
    'perk.web.supplies.parameters.' + user?.id + '.' + scope.workspace?.id
  )
  const parameters = readSupplyParameters(savedParameters)
  const [packaging, setPackaging] = useState<{
    id: string
    item: ReplenishmentItem
  } | null>(null)
  const [boxImport, setBoxImport] = useState(false)
  const [creatingPlan, setCreatingPlan] = useState(false)
  const [planId, setPlanId] = useState<string | null>(null)
  const [savedTab, setTab] = usePreference(
    `perk.web.supplies.view.${user?.id}.${scope.workspace?.id}`
  )
  const tab: SupplyView =
    savedTab === 'history' ||
    savedTab === 'plans' ||
    savedTab === 'destinations'
      ? savedTab
      : 'recommendations'
  const [filter, setFilter] = useState('all')
  const [page, setPage] = useState(0)
  const [urgent, setUrgent] = useState(false)
  const [selectedRecommendation, setRecommendation] =
    useState<ReplenishmentItem | null>(null)
  const [selectedSupply, setSupply] = useState<SupplyCard | null>(null)
  const [savedMode, setSavedMode] = usePreference(
    `perk.web.products.identifier.${user?.id}`
  )
  const mode: IdentifierMode =
    savedMode === 'barcode' || savedMode === 'marketplace'
      ? savedMode
      : 'vendor'
  const supportsRec = scope.selected.some(store =>
    store.features.includes('supplies')
  )
  const supportsHistory = scope.selected.some(store =>
    store.features.includes('supply_history')
  )
  const view: SupplyView =
    !supportsRec || (tab === 'history' && supportsHistory)
      ? 'history'
      : tab === 'destinations' && queryOzonAvailable(scope.selected)
        ? 'destinations'
        : tab === 'plans'
          ? 'plans'
          : 'recommendations'
  const query = useSupplies(view, filter, page, urgent, parameters)
  const plans = usePlans(query.storeId, page, view === 'plans')
  const refresh = useRefreshWorkspace()
  const summary = query.summary.data
  const rec = query.recommendations.data
  const history = query.history.data
  const canRead = scope.can('inventory.read')
  const recommendation =
    selectedRecommendation &&
    (rec?.items.find(
      item =>
        recommendationKey(item) === recommendationKey(selectedRecommendation)
    ) ??
      selectedRecommendation)
  const supply =
    selectedSupply &&
    (history?.items.find(
      item => supplyKey(item) === supplyKey(selectedSupply)
    ) ??
      selectedSupply)
  const changeView = (value: SupplyView) => {
    setTab(value)
    setPage(0)
    setRecommendation(null)
    setSupply(null)
  }
  const filterControl = !scope.store && query.stores.length > 1 && (
    <select
      className='native-select'
      aria-label='Кабинет в списке поставок'
      value={query.filterId || 'all'}
      onChange={event => {
        setFilter(event.target.value)
        setPage(0)
      }}
    >
      <option value='all'>Все кабинеты</option>
      {query.stores.map(store => (
        <option
          key={store.id}
          value={store.id}
        >
          {store.name} · {platformName(store.marketplace)}
        </option>
      ))}
    </select>
  )
  return (
    <AppShell>
      <div className='page-heading'>
        <div className='catalog-title'>
          <h1>Поставки</h1>
          {(summary?.loading ||
            (view === 'history' ? history?.loading : rec?.loading)) && (
            <LoaderCircle
              size={15}
              className='animate-spin text-primary'
              aria-label='Поставки загружаются'
            />
          )}
        </div>
        <Button
          variant='ghost'
          className='refresh-button'
          aria-label='Обновить поставки'
          disabled={scope.loading || query.fetching || !canRead}
          onClick={() => void Promise.all([scope.refresh(), refresh()])}
        >
          <RefreshCw size={15} />
          <span>Обновить</span>
        </Button>
      </div>
      <ErrorNotice
        error={scope.error}
        onRetry={() => void scope.refresh()}
      />
      {scope.loading ? (
        <Loading />
      ) : !canRead ? (
        <Empty title='Нет доступа к поставкам' />
      ) : !scope.stores.length ? (
        <section className='surface welcome-card'>
          <h2>Подключите магазин</h2>
          <ConnectStore />
        </section>
      ) : !query.canRecommendations && !query.canHistory ? (
        <Empty title='Поставки пока недоступны' />
      ) : (
        <>
          {query.canRecommendations && view !== 'destinations' && (
            <>
              <ErrorNotice
                error={query.summary.error}
                onRetry={() => void query.summary.refetch()}
              />
              <SupplySummary
                data={summary}
                pending={query.summary.isPending}
                onUrgent={() => {
                  changeView('recommendations')
                  setUrgent(true)
                  setFilter('all')
                }}
              />
            </>
          )}
          <Tabs
            value={view}
            onValueChange={value => changeView(value as SupplyView)}
            className='supply-tabs'
          >
            <div className='supply-toolbar'>
              <TabsList
                variant='line'
                className='supply-tabs-list'
                aria-label='Раздел поставок'
              >
                {query.canRecommendations && (
                  <TabsTrigger value='recommendations'>
                    Рекомендации
                  </TabsTrigger>
                )}
                {query.canRecommendations && (
                  <>
                    {queryOzonAvailable(scope.selected) && (
                      <TabsTrigger value='destinations'>
                        Кластеры Ozon
                      </TabsTrigger>
                    )}
                    <TabsTrigger value='plans'>Планы</TabsTrigger>
                  </>
                )}
                {query.canHistory && (
                  <TabsTrigger value='history'>Оформленные</TabsTrigger>
                )}
              </TabsList>
              <div className='supply-filters'>
                {scope.admin && (
                  <Button
                    variant='outline'
                    onClick={() => setBoxImport(true)}
                  >
                    Короба из Excel
                  </Button>
                )}
                {filterControl}
                {view === 'recommendations' && (
                  <>
                    <button
                      className='supply-urgent-filter'
                      aria-pressed={urgent}
                      onClick={() => {
                        setUrgent(!urgent)
                        setPage(0)
                      }}
                    >
                      Срочные
                    </button>
                    <select
                      className='native-select'
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
                  </>
                )}
              </div>
            </div>
            <TabsContent value='destinations'>
              <DestinationPanel
                key={query.storeId ?? 'all'}
                storeId={query.storeId}
                parameters={parameters}
                onApply={values => setParameters(JSON.stringify(values))}
                mode={mode}
                onPlan={setPlanId}
                onPackaging={item =>
                  setPackaging({ id: recommendationKey(item), item })
                }
              />
            </TabsContent>
            <TabsContent
              value='recommendations'
              className='supply-recommendations-panel'
            >
              <SupplyControls
                onCreate={scope.admin ? () => setCreatingPlan(true) : undefined}
                key={JSON.stringify(parameters)}
                parameters={parameters}
                busy={
                  query.recommendations.isFetching || query.summary.isFetching
                }
                storeId={query.storeId}
                urgent={urgent}
                canDownload={
                  !!rec?.count &&
                  rec.recommended_units != null &&
                  !query.recommendations.error
                }
                onApply={values => {
                  setParameters(JSON.stringify(values))
                  setPage(0)
                  setRecommendation(null)
                }}
              />

              <ErrorNotice
                error={query.recommendations.error}
                onRetry={() => void query.recommendations.refetch()}
              />
              {query.recommendations.isPending ? (
                <Skeleton className='h-96 w-full rounded-2xl' />
              ) : rec?.items.length ? (
                <RecommendationsTable
                  data={rec}
                  mode={mode}
                  page={page}
                  busy={query.recommendations.isFetching}
                  onPage={setPage}
                  onOpen={setRecommendation}
                  onPackaging={
                    scope.admin
                      ? item => setPackaging({ id: crypto.randomUUID(), item })
                      : undefined
                  }
                />
              ) : !query.recommendations.error ? (
                <section className='surface'>
                  <Empty
                    title={
                      rec?.loading
                        ? 'Рассчитываем потребность'
                        : rec?.recommended_units == null
                          ? 'Расчёт ещё не готов'
                          : urgent
                            ? 'Срочных позиций нет'
                            : 'Пополнение не требуется'
                    }
                  >
                    {(urgent || page > 0) && (
                      <Button
                        variant='ghost'
                        onClick={() => {
                          setUrgent(false)
                          setPage(0)
                        }}
                      >
                        Все рекомендации
                      </Button>
                    )}
                  </Empty>
                </section>
              ) : null}
            </TabsContent>
            <TabsContent value='plans'>
              <div className='supply-plan-toolbar'>
                {scope.admin && (
                  <Button onClick={() => setCreatingPlan(true)}>
                    Новый план
                  </Button>
                )}
              </div>
              <ErrorNotice
                error={plans.error}
                onRetry={() => void plans.refetch()}
              />
              {plans.isPending ? (
                <Skeleton className='h-96 w-full rounded-2xl' />
              ) : plans.data?.items.length ? (
                <PlansTable
                  data={plans.data}
                  page={page}
                  busy={plans.isFetching}
                  onPage={setPage}
                  onOpen={setPlanId}
                />
              ) : !plans.error ? (
                <section className='surface'>
                  <Empty title='Сохранённых планов пока нет'>
                    {page > 0 && (
                      <Button
                        variant='ghost'
                        onClick={() => setPage(0)}
                      >
                        В начало списка
                      </Button>
                    )}
                  </Empty>
                </section>
              ) : null}
            </TabsContent>
            <TabsContent value='history'>
              <ErrorNotice
                error={
                  query.history.error ??
                  (history?.missing_access
                    ? new Error('Проверьте права на поставки в ключе кабинета.')
                    : null)
                }
                onRetry={() => void query.history.refetch()}
              />
              {query.history.isPending ? (
                <Skeleton className='h-96 w-full rounded-2xl' />
              ) : history?.items.length ? (
                <PlacedSuppliesTable
                  data={history}
                  page={page}
                  busy={query.history.isFetching}
                  onPage={setPage}
                  onOpen={setSupply}
                />
              ) : !query.history.error && !history?.missing_access ? (
                <section className='surface'>
                  <Empty
                    title={
                      history?.loading
                        ? 'Загружаем поставки'
                        : history?.incomplete
                          ? 'Поставки ещё не загружены'
                          : 'Оформленных поставок пока нет'
                    }
                  >
                    {page > 0 && (
                      <Button
                        variant='ghost'
                        onClick={() => setPage(0)}
                      >
                        В начало списка
                      </Button>
                    )}
                  </Empty>
                </section>
              ) : null}
            </TabsContent>
          </Tabs>
        </>
      )}
      {creatingPlan && canRead && scope.admin && (
        <CreatePlanDialog
          parameters={parameters}
          storeId={query.storeId}
          urgent={urgent}
          onClose={() => setCreatingPlan(false)}
          onCreated={plan => {
            setCreatingPlan(false)
            changeView('plans')
            setPlanId(plan.id)
          }}
        />
      )}
      {planId && canRead && (
        <PlanEditor
          key={planId}
          id={planId}
          onClose={() => setPlanId(null)}
        />
      )}
      {recommendation && canRead && (
        <RecommendationDetails
          key={recommendationKey(recommendation)}
          item={recommendation}
          summary={summary}
          onClose={() => setRecommendation(null)}
        />
      )}
      {packaging && canRead && scope.admin && (
        <PackagingDialog
          key={packaging.id}
          item={packaging.item}
          onClose={() =>
            setPackaging(current =>
              current?.id === packaging.id ? null : current
            )
          }
        />
      )}
      {supply && canRead && (
        <PlacedSupplyDetails
          key={supplyKey(supply)}
          item={supply}
          onClose={() => setSupply(null)}
        />
      )}
      {boxImport && scope.admin && (
        <CatalogImportDialog
          kind='packaging'
          onClose={() => setBoxImport(false)}
          onSaved={() => void refresh()}
        />
      )}
    </AppShell>
  )
}

function queryOzonAvailable(stores: { marketplace: string }[]) {
  return stores.some(store => store.marketplace === 'ozon')
}
