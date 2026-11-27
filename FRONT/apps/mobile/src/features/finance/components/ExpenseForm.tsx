import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation } from '@tanstack/react-query'
import { Decimal } from 'decimal.js'
import { randomUUID } from 'expo-crypto'
import { useRef } from 'react'
import { useForm, useWatch } from 'react-hook-form'
import { Pressable, View } from 'react-native'
import { z } from 'zod'

import { expensesCreate } from '@app/api'

import { Button, FormField, Notice, Text } from '@/components/ui'

import { errorMessage } from '@/lib/errors'

import { createStyles } from '@/theme'

const categories = [
  ['packaging', 'Упаковка'],
  ['fulfillment', 'Фулфилмент'],
  ['transport', 'Доставка'],
  ['advertising', 'Реклама'],
  ['rent', 'Аренда'],
  ['salary', 'Оплата труда'],
  ['other', 'Прочее']
] as const

const schema = z.object({
  amount: z
    .string()
    .trim()
    .regex(/^\d+(?:[.,]\d{1,4})?$/, 'Укажите сумму, например 1500,50')
    .refine(value => {
      try {
        return new Decimal(value.replace(',', '.')).gt(0)
      } catch {
        return false
      }
    }, 'Сумма должна быть больше нуля')
    .transform(value => value.replace(',', '.')),
  expense_date: z.iso.date('Укажите дату в формате ГГГГ-ММ-ДД'),
  comment: z.string().trim().min(1, 'Напишите, за что расход').max(500),
  category: z.enum([
    'packaging',
    'fulfillment',
    'transport',
    'advertising',
    'rent',
    'salary',
    'other'
  ])
})

export function ExpenseForm({
  workspaceId,
  storeId,
  date,
  currency,
  onSaved
}: {
  workspaceId: string
  storeId: string
  date: string
  currency: string
  onSaved: () => Promise<unknown>
}) {
  const styles = useStyles()
  const form = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
    defaultValues: {
      amount: '',
      expense_date: date,
      comment: '',
      category: 'other'
    }
  })
  const category = useWatch({ control: form.control, name: 'category' })
  const submission = useRef<{ key: string; requestId: string } | null>(null)
  const save = useMutation({
    mutationFn: (values: z.infer<typeof schema>) => {
      const key = JSON.stringify(values)
      if (submission.current?.key !== key)
        submission.current = { key, requestId: randomUUID() }
      return expensesCreate(workspaceId, storeId, {
        ...values,
        currency,
        request_id: submission.current.requestId
      })
    },
    onSuccess: onSaved
  })
  return (
    <>
      {save.error && (
        <Notice
          tone='error'
          message={errorMessage(save.error)}
        />
      )}
      <Text
        variant='caption'
        tone='secondary'
      >
        Только расходы вне WB.
      </Text>
      <FormField
        control={form.control}
        name='amount'
        label={`Сумма, ${currency}`}
        keyboardType='decimal-pad'
      />
      <Text variant='label'>Категория</Text>
      <View style={styles.options}>
        {categories.map(([key, title]) => (
          <Pressable
            key={key}
            accessibilityRole='radio'
            accessibilityState={{ checked: category === key }}
            onPress={() => form.setValue('category', key)}
            style={[styles.option, category === key && styles.selected]}
          >
            <Text
              variant='label'
              tone={category === key ? 'accent' : 'secondary'}
            >
              {title}
            </Text>
          </Pressable>
        ))}
      </View>
      <FormField
        control={form.control}
        name='expense_date'
        label='Дата, ГГГГ-ММ-ДД'
      />
      <FormField
        control={form.control}
        name='comment'
        label='За что расход'
        multiline
      />
      <Button
        title='Добавить расход'
        loading={save.isPending}
        onPress={() => void form.handleSubmit(value => save.mutate(value))()}
      />
    </>
  )
}

const useStyles = createStyles(({ colors, spacing, radius }) => ({
  options: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs },
  option: {
    minHeight: 48,
    justifyContent: 'center',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: radius.control,
    borderWidth: 1,
    borderColor: colors.border
  },
  selected: {
    borderColor: colors.accent,
    backgroundColor: colors.background.screen
  }
}))
