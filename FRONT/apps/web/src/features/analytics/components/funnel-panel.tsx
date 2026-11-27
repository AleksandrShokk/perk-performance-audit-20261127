import { formatNumber, formatPercent } from '@app/analytics/format'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'

import { ReportHint } from '@/features/finance/components/report-hint'

import type { Analytics } from '../hooks/use-analytics'

export function FunnelPanel({
  totals: overall,
  platforms,
  pending
}: {
  totals: Analytics['totals']
  platforms: Analytics['funnels']
  pending: boolean
}) {
  const [marketplace, setMarketplace] = useState<string>('wildberries')
  const selected =
    platforms.find(item => item.marketplace === marketplace) ?? platforms[0]
  const totals = selected?.totals ?? overall
  const stages = [
    ...(selected?.marketplace === 'ozon'
      ? [['Показы', totals.impressions] as const]
      : []),
    ['Просмотры', totals.opens],
    ['В корзину', totals.carts],
    ['Заказано', totals.orders],
    ['Выкуплено', totals.buyouts]
  ] as const
  const maximum = Math.max(1, ...stages.map(([, value]) => Number(value ?? 0)))
  return (
    <section
      className='surface analytics-funnel'
      aria-label='Воронка продаж'
    >
      <div className='section-heading'>
        <h2>Воронка</h2>
        <ReportHint label='О воронке продаж'>
          Выкупы, отмены и возвраты относятся к дате заказа. Доля выкупа —
          выкуплено / (выкуплено + отмены и возвраты). Недоступные показатели
          остаются прочерками.
        </ReportHint>
      </div>
      {platforms.length > 1 && (
        <div
          className='flex gap-2 mt-4'
          role='group'
          aria-label='Площадка воронки'
        >
          {platforms.map(item => (
            <Button
              size='sm'
              variant={
                selected?.marketplace === item.marketplace
                  ? 'secondary'
                  : 'ghost'
              }
              key={item.marketplace}
              aria-pressed={selected?.marketplace === item.marketplace}
              onClick={() => setMarketplace(item.marketplace)}
            >
              {item.title}
            </Button>
          ))}
        </div>
      )}
      <div className='funnel-stages'>
        {stages.map(([label, value]) => (
          <div
            className='funnel-stage'
            key={label}
          >
            <div>
              <span>{label}</span>
              {pending ? (
                <Skeleton className='h-5 w-20' />
              ) : (
                <strong>{formatNumber(value)}</strong>
              )}
            </div>
            <div
              className='funnel-stage-track'
              aria-hidden
            >
              <span
                style={{
                  width:
                    value == null
                      ? '0%'
                      : `${Math.min(100, (Number(value) / maximum) * 100)}%`
                }}
              />
            </div>
          </div>
        ))}
      </div>
      <div className='funnel-conversions'>
        {[
          ['В корзину', totals.cartPercent],
          ['В заказ', totals.orderPercent],
          ['Доля выкупа', totals.buyoutPercent]
        ].map(([label, value]) => (
          <div key={label}>
            <span>{label}</span>
            <strong>{formatPercent(value)}</strong>
          </div>
        ))}
      </div>
    </section>
  )
}
