'use client'

import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation } from '@tanstack/react-query'
import { useRef } from 'react'
import { useForm, useWatch } from 'react-hook-form'

import { expensesCreate } from '@app/api'

import { ChoiceSelect } from '@/components/choice-select'
import { ErrorNotice } from '@/components/feedback'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

import {
  type ExpenseValues,
  expenseCategories,
  expenseSchema
} from '../model/forms'

import { FinanceField } from './finance-field'

export type StoreFormProps = {
  workspaceId: string
  storeId: string
  date: string
  currency: string
  onSaved: () => Promise<unknown>
}
export function ExpenseForm({
  workspaceId,
  storeId,
  date,
  currency,
  onSaved
}: StoreFormProps) {
  const form = useForm<ExpenseValues>({
    resolver: zodResolver(expenseSchema),
    defaultValues: {
      amount: '',
      expense_date: date,
      comment: '',
      category: 'other',
      custom_category: ''
    }
  })
  const category = useWatch({ control: form.control, name: 'category' })
  const submission = useRef<{ payload: string; id: string } | null>(null)
  const save = useMutation({
    mutationFn: (values: ExpenseValues) => {
      const payload = JSON.stringify(values)
      if (submission.current?.payload !== payload)
        submission.current = { payload, id: crypto.randomUUID() }
      return expensesCreate(workspaceId, storeId, {
        ...values,
        category: values.custom_category ? 'other' : values.category,
        currency,
        request_id: submission.current.id
      })
    },
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
      <div className='date-fields'>
        <FinanceField
          label={`Сумма, ${currency}`}
          error={errors.amount?.message}
        >
          <Input
            inputMode='decimal'
            autoFocus
            {...form.register('amount')}
          />
        </FinanceField>
        <FinanceField
          label='Дата расхода'
          error={errors.expense_date?.message}
        >
          <Input
            type='date'
            {...form.register('expense_date')}
          />
        </FinanceField>
      </div>
      <FinanceField
        label='Категория'
        error={errors.category?.message}
      >
        <ChoiceSelect
          label='Категория расхода'
          value={category}
          onChange={value =>
            form.setValue('category', value as ExpenseValues['category'])
          }
          options={expenseCategories.map(([value, label]) => ({
            value,
            label
          }))}
        />
      </FinanceField>
      <FinanceField
        label='Своя статья расходов'
        error={errors.custom_category?.message}
      >
        <Input
          placeholder='Например, фотосъёмка'
          maxLength={100}
          {...form.register('custom_category')}
        />
      </FinanceField>
      <FinanceField
        label='За что расход'
        error={errors.comment?.message}
      >
        <textarea
          className='finance-input'
          rows={3}
          maxLength={500}
          {...form.register('comment')}
        />
      </FinanceField>
      <Button
        type='submit'
        disabled={save.isPending}
      >
        {save.isPending ? 'Сохраняем…' : 'Сохранить расход'}
      </Button>
    </form>
  )
}
