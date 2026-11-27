import { formatUnits } from '@app/analytics/format'

import type { InventoryAmounts, InventoryOverview } from '@app/api'

import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'

import { ReportHint } from '@/features/finance/components/report-hint'
import { financeMoney } from '@/features/finance/model/finance-format'

import { stockBasisTitle, stockCover } from '../model/stock'

export function StockChannel({
  title,
  amount,
  currency,
  canCost,
  pending
}: {
  title: string
  amount?: InventoryAmounts
  currency?: string
  canCost: boolean
  pending?: boolean
}) {
  return (
    <div className='stock-channel'>
      <h2>{title}</h2>
      {pending ? (
        <Skeleton className='h-9 w-3/4' />
      ) : (
        <strong className='stock-retail'>
          {financeMoney(amount?.retail_value, currency)}
        </strong>
      )}
      <div className='stock-channel-units'>
        {pending ? '—' : formatUnits(amount?.units)}
        {amount?.retail_value != null && amount.retail_complete === false && (
          <ReportHint label={`Об оценке ${title}`}>
            Стоимость рассчитана по позициям с загруженной ценой продавца.
          </ReportHint>
        )}
      </div>
      {canCost && (
        <div className='stock-channel-cost'>
          <span>
            По себестоимости
            {amount?.cost_value != null && !amount.cost_complete && (
              <ReportHint label={`О себестоимости ${title}`}>
                Сумма по себестоимости неполная: учтены позиции с заполненной
                ценой.
              </ReportHint>
            )}
          </span>
          {pending ? (
            <Skeleton className='h-5 w-1/2' />
          ) : (
            <strong>{financeMoney(amount?.cost_value, currency)}</strong>
          )}
        </div>
      )}
    </div>
  )
}
export function StockSummary({
  data,
  pending,
  canCost,
  onCabinets,
  canCabinets
}: {
  data?: InventoryOverview
  pending?: boolean
  canCost: boolean
  onCabinets: () => void
  canCabinets: boolean
}) {
  const separateCover = canCabinets && data?.turnover_supported === false
  return (
    <section
      className='surface stock-summary'
      aria-label='Сводка остатков'
    >
      <StockChannel
        title='FBO'
        amount={data?.fbo}
        currency={data?.currency}
        canCost={canCost}
        pending={pending}
      />
      <StockChannel
        title='FBS'
        amount={data?.fbs}
        currency={data?.currency}
        canCost={canCost}
        pending={pending}
      />
      <div className='stock-cover-summary'>
        <div>
          <h2>{stockBasisTitle(data?.turnover_basis)}</h2>
          <ReportHint label='О запасе в днях'>
            Для выбранной схемы: WB — заказы с учётом времени наличия. Ozon FBO
            — спрос площадки, FBS — заказы за 28 дней. Общий показатель разных
            методов не усредняется.
          </ReportHint>
        </div>
        {pending ? (
          <Skeleton className='h-10 w-1/2' />
        ) : separateCover ? (
          <Button
            variant='secondary'
            onClick={onCabinets}
          >
            По кабинетам
          </Button>
        ) : (
          <strong>
            {data?.turnover_days == null && data?.turnover_loading
              ? 'Загружаем…'
              : data?.turnover_supported === false
                ? '—'
                : stockCover(data?.turnover_days)}
          </strong>
        )}

        {data?.aggregation_status === 'warehouse_mapping_required' && (
          <ReportHint label='Об общей сумме FBS'>
            Общий физический склад нельзя посчитать несколько раз. Выберите
            кабинет или настройте учёт FBS.
          </ReportHint>
        )}
      </div>
    </section>
  )
}
