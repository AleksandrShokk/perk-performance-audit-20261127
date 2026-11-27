import { formatMoney } from '@app/analytics/format'

import type { FinanceOverview } from '@app/api'

import { Skeleton } from '@/components/ui/skeleton'

import { financeMoney } from '../model/finance-format'

export function FinanceSummary({
  report,
  pending,
  canProfit,
  precise = true
}: {
  report?: FinanceOverview
  pending?: boolean
  canProfit: boolean
  precise?: boolean
}) {
  const metrics = [
    {
      key: 'revenue',
      title: 'Выручка продавца',
      value: report?.totals.seller_revenue
    },
    {
      key: 'expenses',
      title: 'Расходы',
      value: report?.totals.expenses_before_tax
    },
    ...(canProfit
      ? [
          {
            key: 'profit',
            title: 'Прибыль до налогов',
            value: report?.totals.profit_before_tax
          }
        ]
      : []),
    {
      key: 'settlement',
      title: 'К перечислению',
      value: report?.totals.settlement
    }
  ]
  return (
    <div
      className={`finance-metrics${canProfit ? '' : ' without-profit'}`}
      aria-label='Финансовая сводка'
      aria-busy={pending}
    >
      {metrics.map(metric => (
        <div
          key={metric.key}
          className={`finance-metric ${metric.key === 'profit' ? 'profit' : ''}`}
        >
          <span>{metric.title}</span>
          {pending ? (
            <Skeleton className='h-8 w-3/4' />
          ) : (
            <strong>
              {precise
                ? financeMoney(metric.value, report?.currency)
                : formatMoney(metric.value, report?.currency)}
            </strong>
          )}
        </div>
      ))}
    </div>
  )
}
