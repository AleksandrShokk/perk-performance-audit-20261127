'use client'

import type { DateRange } from '@app/analytics/dates'
import { useState } from 'react'

import { financeOverviewExport } from '@app/api'

import { ChoiceSelect } from '@/components/choice-select'
import { ReportExportButton } from '@/components/report-export-button'

import { useWorkspace } from '@/features/workspace/workspace-provider'

export function FinanceExport({
  range,
  disabled
}: {
  range: DateRange
  disabled: boolean
}) {
  const scope = useWorkspace()
  const [format, setFormat] = useState<'xlsx' | 'csv'>('xlsx')
  if (!scope.can('reports.export')) return null
  return (
    <div className='catalog-heading-actions'>
      <ChoiceSelect
        label='Формат финансовой сводки'
        value={format}
        onChange={value => setFormat(value as typeof format)}
        options={[
          { value: 'xlsx', label: 'Excel' },
          { value: 'csv', label: 'CSV' }
        ]}
      />
      <ReportExportButton
        label='Скачать сводку'
        disabled={disabled}
        filename={`perk-finance-${range.date_from}-${range.date_to}.${format}`}
        request={signal =>
          financeOverviewExport(
            scope.workspace!.id,
            { ...range, store_id: scope.store?.id, format },
            { signal, responseType: 'blob', timeout: 90000 }
          )
        }
      />
    </div>
  )
}
