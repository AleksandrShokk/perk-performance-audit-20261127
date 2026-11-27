'use client'

import { moscowToday } from '@app/analytics/dates'
import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import { useForm, useWatch } from 'react-hook-form'

import {
  type ProductItem,
  type ProductVariant,
  costsSave,
  variantCostsSave
} from '@app/api'

import { ChoiceSelect } from '@/components/choice-select'
import { ErrorNotice } from '@/components/feedback'
import { displayDate, inputDate } from '@/components/range-calendar'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

import { FinanceField } from '@/features/finance/components/finance-field'
import { ReportHint } from '@/features/finance/components/report-hint'
import { useRefreshFinance } from '@/features/finance/hooks/use-finance'

import { sizeLabel } from '../model/catalog'
import { type CostValues, costSchema } from '../model/cost-schema'

export function CostEditor({
  product,
  variant,
  workspaceId,
  marketplace,
  currency,
  onSaved,
  onCancel
}: {
  product: ProductItem
  variant?: ProductVariant
  workspaceId: string
  marketplace: string
  currency: string
  onSaved: () => void
  onCancel: () => void
}) {
  const refresh = useRefreshFinance()
  const mounted = useRef(true)
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])
  const form = useForm<CostValues>({
    resolver: zodResolver(costSchema),
    defaultValues: {
      amount: variant?.unit_cost ?? '',
      effective_from: moscowToday(),
      barcode: variant?.barcodes[0] ?? ''
    }
  })
  const [effectiveFrom, barcode] = useWatch({
    control: form.control,
    name: ['effective_from', 'barcode']
  })
  const isOzon = marketplace === 'ozon'
  const save = useMutation({
    mutationFn: async (values: CostValues): Promise<void> => {
      if (isOzon) {
        if (!variant?.id) throw new Error('Нет идентификатора варианта')
        await variantCostsSave(workspaceId, product.store_id, {
          variant_id: variant.id,
          amount: values.amount,
          currency,
          effective_from: values.effective_from
        })
        return
      }
      await costsSave(workspaceId, product.store_id, {
        ...values,
        currency,
        nm_id: product.nm_id
      })
    },
    onSuccess: async () => {
      await refresh()
      if (mounted.current) onSaved()
    }
  })
  const errors = form.formState.errors
  return (
    <form
      className='form-stack product-cost-editor'
      aria-label='Изменение себестоимости'
      onSubmit={form.handleSubmit(values => {
        if (!save.isPending) save.mutate(values)
      })}
      noValidate
    >
      <div className='product-editor-heading'>
        <h3>Себестоимость</h3>
        <ReportHint label='О применении цены'>
          Цена действует с выбранной даты. У WB цена для штрихкода имеет
          приоритет над общей ценой товара.
        </ReportHint>
      </div>
      <ErrorNotice error={save.error} />
      <div className='date-fields'>
        <FinanceField
          label={`Цена, ${currency}`}
          error={errors.amount?.message}
        >
          <Input
            autoFocus
            inputMode='decimal'
            {...form.register('amount')}
          />
        </FinanceField>
        <FinanceField
          label='Действует с'
          error={errors.effective_from?.message}
        >
          <Input
            placeholder='ДД.ММ.ГГГГ'
            inputMode='numeric'
            value={displayDate(effectiveFrom)}
            onChange={event =>
              form.setValue('effective_from', inputDate(event.target.value), {
                shouldValidate: true
              })
            }
          />
        </FinanceField>
      </div>
      {!isOzon && (
        <FinanceField label='Применить к'>
          <ChoiceSelect
            label='Размер для себестоимости'
            value={barcode || 'all'}
            onChange={value =>
              form.setValue('barcode', value === 'all' ? '' : value)
            }
            options={[
              { value: 'all', label: 'Всем размерам' },
              ...product.variants.flatMap(item =>
                item.barcodes
                  .slice(0, 1)
                  .map(code => ({ value: code, label: sizeLabel(item) }))
              )
            ]}
          />
        </FinanceField>
      )}
      <div className='product-editor-actions'>
        <Button
          type='submit'
          disabled={save.isPending}
        >
          {save.isPending ? 'Сохраняем…' : 'Сохранить себестоимость'}
        </Button>
        <Button
          variant='ghost'
          type='button'
          disabled={save.isPending}
          onClick={onCancel}
        >
          Отмена
        </Button>
      </div>
    </form>
  )
}
