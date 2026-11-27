import { formatNumber, formatUnits } from '@app/analytics/format'
import { ArrowLeft, RefreshCw } from 'lucide-react'
import { useState } from 'react'

import type { SupplyParameters } from '@app/schemas'

import type { ReplenishmentItem, SupplyDestination } from '@app/api'

import { Empty, ErrorNotice } from '@/components/feedback'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'

import { ReportHint } from '@/features/finance/components/report-hint'
import {
  type IdentifierMode,
  platformName
} from '@/features/products/model/catalog'
import { useWorkspace } from '@/features/workspace/workspace-provider'

import { useDestinations } from '../hooks/use-destinations'

import { CreatePlanDialog } from './create-plan-dialog'
import { SupplyControls } from './supply-controls'
import { RecommendationDetails } from './supply-details'
import { SupplySummary } from './supply-summary'
import { RecommendationsTable } from './supply-tables'

export function DestinationPanel({
  storeId,
  parameters,
  onApply,
  mode,
  onPlan,
  onPackaging
}: {
  storeId?: string
  parameters: SupplyParameters
  onApply: (value: SupplyParameters) => void
  mode: IdentifierMode
  onPlan: (id: string) => void
  onPackaging: (item: ReplenishmentItem) => void
}) {
  const scope = useWorkspace()
  const [selected, setSelected] = useState<SupplyDestination | null>(null)
  const [urgent, setUrgent] = useState(false)
  const [page, setPage] = useState(0),
    [creating, setCreating] = useState(false)
  const [detail, setDetail] = useState<ReplenishmentItem | null>(null)
  const { list, rows, refresh } = useDestinations({
    storeId,
    selected,
    parameters,
    page,
    urgent
  })
  const data = rows.data
  const choose = (item: SupplyDestination | null) => {
    setUrgent(false)
    setSelected(item)
    setPage(0)
    setDetail(null)
  }
  return (
    <>
      <div className='surface supply-destination-toolbar'>
        {selected ? (
          <Button
            variant='ghost'
            onClick={() => choose(null)}
          >
            <ArrowLeft size={16} />
            Все направления
          </Button>
        ) : (
          <span className='supply-destination-title'>
            <strong>Кластеры Ozon</strong>
            <ReportHint label='О направлениях поставки'>
              Нативные кластеры Ozon. Излишки одного направления не закрывают
              дефицит другого. Доля спроса — по данным площадки, общий спрос —
              по всем заказам за 28 календарных дней.
            </ReportHint>
          </span>
        )}
        {list.data?.loading && (
          <span
            className='muted'
            role='status'
          >
            Загружено товаров: {formatNumber(list.data.loaded_products)} из{' '}
            {formatNumber(list.data.total_products)}
          </span>
        )}
        <Button
          variant='outline'
          disabled={refresh.isPending || list.isPending}
          onClick={() => refresh.mutate()}
        >
          <RefreshCw size={15} />
          Загрузить направления
        </Button>
      </div>
      <ErrorNotice
        error={
          list.error ||
          refresh.error ||
          (list.data?.failed_products
            ? new Error(
                'Не удалось обновить часть направлений. Повторите загрузку.'
              )
            : null)
        }
        onRetry={() => void list.refetch()}
      />
      {selected ? (
        <>
          <div className='supply-destination-heading'>
            <h2>{selected.name}</h2>
            <span className='muted'>
              {selected.store_name} · {platformName(selected.marketplace)}
            </span>
          </div>
          <SupplySummary
            data={data}
            pending={rows.isPending}
            onUrgent={() => {
              setUrgent(value => !value)
              setPage(0)
            }}
          />
          <SupplyControls
            key={JSON.stringify(parameters)}
            parameters={parameters}
            storeId={selected.store_id}
            destinationId={selected.id}
            urgent={urgent}
            busy={rows.isFetching}
            canDownload={!!data?.count && !rows.error}
            onApply={value => {
              onApply(value)
              setPage(0)
            }}
            onCreate={scope.admin ? () => setCreating(true) : undefined}
          />
          <ErrorNotice
            error={rows.error}
            onRetry={() => void rows.refetch()}
          />
          {rows.isPending ? (
            <Skeleton className='h-80 w-full rounded-2xl' />
          ) : data?.items.length ? (
            <RecommendationsTable
              data={data}
              mode={mode}
              page={page}
              busy={rows.isFetching}
              onPage={setPage}
              onOpen={setDetail}
              onPackaging={scope.admin ? onPackaging : undefined}
            />
          ) : (
            <Empty
              title={
                data?.recommended_units == null
                  ? 'Нет данных для расчёта'
                  : 'Пополнение не требуется'
              }
            />
          )}
        </>
      ) : list.isPending ? (
        <Skeleton className='h-80 w-full rounded-2xl' />
      ) : list.data?.items.length ? (
        <section
          className='supply-destination-grid'
          aria-label='Направления поставок'
        >
          {list.data.items
            .filter(item => item.marketplace === 'ozon')
            .map(item => (
              <button
                className='surface supply-destination-card'
                key={item.store_id + ':' + item.id}
                onClick={() => choose(item)}
                aria-label={
                  'Открыть направление ' + item.name + ' · ' + item.store_name
                }
              >
                <span className='muted'>
                  {item.store_name} · {platformName(item.marketplace)}
                </span>
                <h3>{item.name}</h3>
                <strong>{formatUnits(item.recommended_units)}</strong>
                <span className='muted'>
                  Позиций:{' '}
                  {formatNumber(
                    item.recommended_units == null ? null : item.product_count
                  )}
                </span>
              </button>
            ))}
        </section>
      ) : (
        <Empty
          title={
            list.data?.loading
              ? 'Загружаем направления'
              : list.data?.failed_products
                ? 'Не удалось загрузить направления'
                : 'Направления ещё не загружены'
          }
        />
      )}
      {detail && (
        <RecommendationDetails
          item={detail}
          summary={data}
          onClose={() => setDetail(null)}
        />
      )}
      {creating && selected && (
        <CreatePlanDialog
          parameters={parameters}
          storeId={selected.store_id}
          destination={selected}
          urgent={urgent}
          onClose={() => setCreating(false)}
          onCreated={plan => {
            setCreating(false)
            onPlan(plan.id)
          }}
        />
      )}
    </>
  )
}
