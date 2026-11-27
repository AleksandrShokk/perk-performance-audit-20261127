import { zodResolver } from '@hookform/resolvers/zod'
import { Download } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'

import { type SupplyParameters, supplyParametersSchema } from '@app/schemas'

import { inventoryReplenishmentExport } from '@app/api'

import { ChoiceSelect } from '@/components/choice-select'
import { ErrorNotice } from '@/components/feedback'
import { FormField } from '@/components/form-field'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

import { useWorkspace } from '@/features/workspace/workspace-provider'

import { useProtectedAction } from '@/hooks/use-protected-action'

import { downloadFile } from '@/lib/download'

export function SupplyControls({
  parameters,
  onApply,
  storeId,
  destinationId,
  urgent,
  busy,
  canDownload,
  onCreate
}: {
  parameters: SupplyParameters
  onApply: (value: SupplyParameters) => void
  storeId?: string
  destinationId?: string
  urgent: boolean
  busy: boolean
  canDownload: boolean
  onCreate?: () => void
}) {
  const scope = useWorkspace()
  const [format, setFormat] = useState<'csv' | 'xlsx'>('xlsx')
  const form = useForm({
    resolver: zodResolver(supplyParametersSchema),
    defaultValues: parameters
  })
  const download = useProtectedAction(
    signal =>
      inventoryReplenishmentExport(
        scope.workspace!.id,
        {
          ...parameters,
          format,
          store_id: storeId,
          destination_id: destinationId,
          urgent_only: urgent
        },
        { signal, responseType: 'blob' }
      ),
    file => downloadFile(file, `perk-supply-requirements.${format}`),
    { refresh: false }
  )
  return (
    <section
      className='surface supply-controls'
      aria-label='Параметры поставки'
    >
      <form
        onSubmit={form.handleSubmit(value => {
          onApply(value)
          form.reset(value)
        })}
      >
        <fieldset disabled={busy || download.isPending}>
          <FormField
            label='Запас после поступления, дней'
            error={form.formState.errors.target_days?.message}
          >
            <Input
              type='number'
              inputMode='numeric'
              min={1}
              max={180}
              step={1}
              {...form.register('target_days', { valueAsNumber: true })}
            />
          </FormField>
          <FormField
            label='Доставка и приёмка, дней'
            error={form.formState.errors.lead_time_days?.message}
          >
            <Input
              type='number'
              inputMode='numeric'
              min={0}
              max={90}
              step={1}
              {...form.register('lead_time_days', { valueAsNumber: true })}
            />
          </FormField>
          <label className='supply-fbs-control'>
            <input
              type='checkbox'
              role='switch'
              className='sr-only'
              {...form.register('include_fbs')}
            />
            <span
              className='supply-fbs-switch'
              aria-hidden='true'
            >
              <span />
            </span>
            <span>Вычитать остатки FBS</span>
          </label>
          <Button
            type='submit'
            variant='outline'
            disabled={!form.formState.isDirty || busy}
          >
            Рассчитать
          </Button>
        </fieldset>
      </form>
      {onCreate && (
        <Button
          disabled={busy || !canDownload}
          onClick={onCreate}
        >
          Создать план
        </Button>
      )}
      {scope.can('reports.export') && (
        <ChoiceSelect
          label='Формат выгрузки поставки'
          value={format}
          onChange={value => setFormat(value as 'csv' | 'xlsx')}
          options={[
            { value: 'xlsx', label: 'Excel' },
            { value: 'csv', label: 'CSV' }
          ]}
        />
      )}
      {scope.can('reports.export') && (
        <Button
          variant='outline'
          disabled={busy || download.isPending || !canDownload}
          onClick={() => download.mutate()}
        >
          <Download size={15} />
          {download.isPending ? 'Готовим файл…' : 'Выгрузить потребность'}
        </Button>
      )}
      <ErrorNotice error={download.error} />
    </section>
  )
}
