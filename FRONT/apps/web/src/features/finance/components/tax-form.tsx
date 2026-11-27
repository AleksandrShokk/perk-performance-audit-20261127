'use client'

import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useForm } from 'react-hook-form'

import { type TaxSettingView, taxSettingsList, taxSettingsSave } from '@app/api'

import { ErrorNotice, Loading } from '@/components/feedback'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

import { useAuth } from '@/features/auth/auth-provider'
import { useWorkspace } from '@/features/workspace/workspace-provider'

import { type TaxValues, taxRegimes, taxSchema } from '../model/forms'

import type { StoreFormProps } from './expense-form'
import { FinanceField } from './finance-field'

export function TaxForm(props: StoreFormProps) {
  const { user } = useAuth()
  const scope = useWorkspace()
  const settings = useQuery({
    queryKey: [
      'user',
      user?.id,
      props.workspaceId,
      'finance',
      scope.accessKey,
      props.storeId,
      'tax-settings'
    ],
    queryFn: ({ signal }) =>
      taxSettingsList(props.workspaceId, props.storeId, { signal })
  })
  if (settings.isPending) return <Loading />
  if (settings.error)
    return (
      <ErrorNotice
        error={settings.error}
        onRetry={() => void settings.refetch()}
      />
    )
  const initial = settings.data
    ?.filter(row => row.effective_from <= props.date)
    .sort((a, b) => b.effective_from.localeCompare(a.effective_from))[0]
  return (
    <TaxFields
      {...props}
      initial={initial}
    />
  )
}
function TaxFields({
  workspaceId,
  storeId,
  date,
  onSaved,
  initial
}: StoreFormProps & { initial?: TaxSettingView }) {
  const form = useForm<TaxValues>({
    resolver: zodResolver(taxSchema),
    defaultValues: {
      effective_from: initial?.effective_from ?? date,
      regime: initial?.regime ?? 'none',
      rate: initial?.rate ?? '0',
      vat_rate: initial?.vat_rate ?? '0',
      income_base: initial?.income_base ?? 'revenue'
    }
  })
  const save = useMutation({
    mutationFn: (values: TaxValues) =>
      taxSettingsSave(workspaceId, storeId, values),
    onSuccess: onSaved
  })
  const errors = form.formState.errors
  return (
    <form
      className='form-stack finance-form'
      onSubmit={form.handleSubmit(values => save.mutate(values))}
      noValidate
    >
      <ErrorNotice error={save.error} />
      <FinanceField label='Система налогообложения'>
        <select
          className='finance-input'
          {...form.register('regime')}
          onChange={event => {
            form.setValue('regime', event.target.value as TaxValues['regime'])
            if (event.target.value === 'none') {
              form.setValue('rate', '0')
              form.setValue('vat_rate', '0')
            }
          }}
        >
          {taxRegimes.map(([key, title]) => (
            <option
              key={key}
              value={key}
            >
              {title}
            </option>
          ))}
        </select>
      </FinanceField>
      <div className='date-fields'>
        <FinanceField
          label='Ставка налога, %'
          error={errors.rate?.message}
        >
          <Input
            inputMode='decimal'
            {...form.register('rate')}
          />
        </FinanceField>
        <FinanceField
          label='НДС в цене, %'
          error={errors.vat_rate?.message}
        >
          <Input
            inputMode='decimal'
            {...form.register('vat_rate')}
          />
        </FinanceField>
      </div>
      <FinanceField label='Налоговая база'>
        <select
          className='finance-input'
          {...form.register('income_base')}
        >
          <option value='revenue'>Выручка от реализации</option>
          <option value='payout'>Перечисление за товар</option>
        </select>
      </FinanceField>
      <FinanceField
        label='Действует с'
        error={errors.effective_from?.message}
      >
        <Input
          type='date'
          {...form.register('effective_from')}
        />
      </FinanceField>
      <Button
        type='submit'
        disabled={save.isPending}
      >
        {save.isPending ? 'Сохраняем…' : 'Сохранить настройки'}
      </Button>
    </form>
  )
}
