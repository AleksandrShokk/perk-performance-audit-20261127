'use client'

import { type DateRange } from '@app/analytics/dates'
import { useState } from 'react'

import { analyticsSalesExport } from '@app/api'

import { ChoiceSelect } from '@/components/choice-select'
import { ErrorNotice } from '@/components/feedback'
import { Button } from '@/components/ui/button'

import { useWorkspace } from '@/features/workspace/workspace-provider'

import { useProtectedAction } from '@/hooks/use-protected-action'

import { downloadFile } from '@/lib/download'

export function AnalyticsExport({
  range,
  priceBasis = 'customer'
}: {
  range: DateRange
  priceBasis?: 'customer' | 'seller'
}) {
  const scope = useWorkspace(),
    [format, setFormat] = useState<'csv' | 'xlsx'>('xlsx'),
    [kind, setKind] = useState<'products' | 'days' | 'sizes'>('products')
  const download = useProtectedAction(
    signal =>
      analyticsSalesExport(
        scope.workspace!.id,
        {
          ...range,
          store_id: scope.store?.id,
          format,
          granularity: kind,
          price_basis: priceBasis
        },
        { signal, responseType: 'blob' }
      ),
    file =>
      downloadFile(
        file,
        `perk-sales-${range.date_from}-${range.date_to}.${format}`
      ),
    { refresh: false }
  )
  if (!scope.can('reports.export')) return null
  return (
    <div className='catalog-heading-actions'>
      <ChoiceSelect
        label='Состав статистики'
        value={kind}
        onChange={value => setKind(value as typeof kind)}
        options={[
          { value: 'products', label: 'По товарам' },
          { value: 'days', label: 'По дням' },
          {
            value: 'sizes',
            label: 'По размерам WB',
            disabled:
              !scope.selected.length ||
              scope.selected.some(store => store.marketplace !== 'wildberries')
          }
        ]}
      />
      <ChoiceSelect
        label='Формат статистики'
        value={format}
        onChange={value => setFormat(value as typeof format)}
        options={[
          { value: 'xlsx', label: 'Excel' },
          { value: 'csv', label: 'CSV' }
        ]}
      />
      <Button
        variant='outline'
        disabled={download.isPending}
        onClick={() => download.mutate()}
      >
        {download.isPending ? 'Готовим файл…' : 'Скачать статистику'}
      </Button>
      {kind === 'sizes' && (
        <small className='text-muted-foreground'>
          Заказы — по дате заказа, выкупы — по дате продажи. Только сохранённая
          история WB.
        </small>
      )}
      <ErrorNotice error={download.error} />
    </div>
  )
}
