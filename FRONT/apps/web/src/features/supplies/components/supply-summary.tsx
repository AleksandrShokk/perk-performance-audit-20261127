import { formatNumber, formatUnits } from '@app/analytics/format'

import type { ReplenishmentOverview } from '@app/api'

import { Skeleton } from '@/components/ui/skeleton'

import { ReportHint } from '@/features/finance/components/report-hint'

export function SupplySummary({
  data,
  pending,
  onUrgent
}: {
  data?: ReplenishmentOverview
  pending: boolean
  onUrgent: () => void
}) {
  return (
    <section
      className='surface supply-overview'
      aria-label='Общая потребность в поставке'
    >
      <div>
        <span className='supply-metric-label'>
          Рекомендуем довезти
          <ReportHint label='О расчёте потребности'>
            Запас FBO на {data?.target_days ?? 30} дней после поступления. Спрос
            — все заказы FBO + FBS за 28 календарных дней. Доставка и приёмка —{' '}
            {data?.lead_time_days ?? 7} дней. Оформленные партии учитываются по
            датам; кратность коробов — в конце расчёта.
            {data?.include_fbs ? ' Остатки FBS вычитаются из потребности.' : ''}
          </ReportHint>
        </span>
        {pending ? (
          <Skeleton className='h-10 w-40' />
        ) : (
          <strong>{formatUnits(data?.recommended_units)}</strong>
        )}
      </div>
      <div>
        <span className='supply-metric-label'>Позиций к пополнению</span>
        {pending ? (
          <Skeleton className='h-10 w-24' />
        ) : (
          <strong>{formatNumber(data?.product_count)}</strong>
        )}
      </div>
      <button
        className='supply-urgent-metric'
        onClick={onUrgent}
        disabled={pending || !data?.urgent_count}
      >
        <span className='supply-metric-label'>Срочных позиций</span>
        {pending ? (
          <Skeleton className='h-10 w-24' />
        ) : (
          <strong>{formatNumber(data?.urgent_count)}</strong>
        )}
      </button>
      <span className='supply-target'>
        Запас на {data?.target_days ?? 30} дней
      </span>
    </section>
  )
}
