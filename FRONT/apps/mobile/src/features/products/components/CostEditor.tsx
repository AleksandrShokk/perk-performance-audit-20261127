import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import { useForm, useWatch } from 'react-hook-form'
import { Pressable, View } from 'react-native'
import type { z } from 'zod'

import {
  type ProductItem,
  type ProductVariant,
  costsSave,
  variantCostsSave
} from '@app/api'

import { Button, FormField, Notice, Text } from '@/components/ui'

import { toISODate } from '@/lib/dates'
import { errorMessage } from '@/lib/errors'

import { useRefreshProducts } from '../hooks/useProducts'
import { costSchema } from '../model/costSchema'
import { variantLabel } from '../model/productMetrics'

import { createStyles } from '@/theme'

type Values = z.infer<typeof costSchema>

export function CostEditor({
  workspaceId,
  product,
  variant,
  currency,
  onSaved,
  onCancel
}: {
  workspaceId: string
  product: ProductItem
  variant?: ProductVariant
  currency: string
  onSaved: () => Promise<void>
  onCancel: () => void
}) {
  const styles = useStyles()
  const mounted = useRef(true)
  const refresh = useRefreshProducts()
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])
  const form = useForm<Values>({
    resolver: zodResolver(costSchema),
    defaultValues: {
      amount: variant?.unit_cost ?? '',
      effective_from: toISODate(new Date()),
      barcode: variant?.barcodes[0] ?? ''
    }
  })
  const isOzon = product.marketplace === 'ozon'
  const barcode = useWatch({ control: form.control, name: 'barcode' })
  const choices = [
    { value: '', label: 'Все размеры' },
    ...product.variants.flatMap(row =>
      row.barcodes.map(code => ({
        value: code,
        label: `${variantLabel(row.size, row.chrt_id)} · ${code}`
      }))
    )
  ]
  const save = useMutation({
    mutationFn: async (values: Values) => {
      if (isOzon) {
        const id = (variant ?? product.variants[0])?.id
        if (!id) throw new Error('Выберите вариант товара')
        await variantCostsSave(workspaceId, product.store_id, {
          variant_id: id,
          amount: values.amount.replace(',', '.'),
          currency,
          effective_from: values.effective_from
        })
      } else {
        await costsSave(workspaceId, product.store_id, {
          ...values,
          amount: values.amount.replace(',', '.'),
          currency,
          nm_id: product.nm_id
        })
      }
    },
    onSuccess: async () => {
      if (mounted.current) await onSaved()
      else void refresh()
    }
  })
  return (
    <View style={styles.form}>
      <Text variant='bodyStrong'>{product.title}</Text>
      <Text
        variant='label'
        tone='secondary'
      >
        Цена за одну единицу · {currency}
      </Text>
      {save.error && (
        <Notice
          tone='error'
          message={errorMessage(save.error)}
        />
      )}
      <FormField
        control={form.control}
        name='amount'
        label='Себестоимость'
        keyboardType='decimal-pad'
      />
      <FormField
        control={form.control}
        name='effective_from'
        label='Действует с (ГГГГ-ММ-ДД)'
        placeholder='2026-11-02'
        keyboardType='numbers-and-punctuation'
      />
      {!isOzon && (
        <>
          <Text variant='labelStrong'>Размер / штрихкод</Text>
          {choices.map(option => (
            <Pressable
              key={option.value}
              onPress={() => form.setValue('barcode', option.value)}
              accessibilityRole='radio'
              accessibilityState={{ checked: barcode === option.value }}
              style={[
                styles.option,
                barcode === option.value && styles.selected
              ]}
            >
              <Text variant='label'>{option.label}</Text>
            </Pressable>
          ))}
          {!barcode && product.variants.some(row => row.unit_cost != null) && (
            <Text
              variant='caption'
              tone='secondary'
            >
              Отдельные цены размеров имеют приоритет над общей.
            </Text>
          )}
        </>
      )}
      <Button
        title='Сохранить цену'
        loading={save.isPending}
        onPress={() => void form.handleSubmit(values => save.mutate(values))()}
      />
      <Button
        title='Назад к товару'
        variant='ghost'
        disabled={save.isPending}
        onPress={onCancel}
      />
    </View>
  )
}
const useStyles = createStyles(({ colors, spacing, radius, sizes }) => ({
  form: { gap: spacing.md },
  option: {
    minHeight: sizes.touchTarget,
    padding: spacing.sm,
    justifyContent: 'center',
    borderRadius: radius.control,
    backgroundColor: colors.background.screen
  },
  selected: { backgroundColor: colors.accentSoft }
}))
