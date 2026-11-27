import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useForm, useWatch } from 'react-hook-form'
import { Pressable, View } from 'react-native'
import { z } from 'zod'

import { type TaxSettingView, taxSettingsList, taxSettingsSave } from '@app/api'

import {
  Button,
  FormField,
  Notice,
  Skeleton,
  Text
} from '@/components/ui'

import { useAuth } from '@/features/auth/providers/AuthProvider'

import { errorMessage } from '@/lib/errors'

import { createStyles } from '@/theme'

const regimes = [
  ['usn_income', 'УСН «Доходы»'],
  ['usn_income_expense', 'УСН «Доходы − расходы»'],
  ['profit', 'Налог на прибыль'],
  ['none', 'Без расчёта налогов']
] as const
const rate = z
  .string()
  .trim()
  .regex(/^\d+(?:[.,]\d{1,2})?$/, 'Укажите процент')
  .refine(value => Number(value.replace(',', '.')) <= 100, 'Не больше 100%')
  .transform(value => value.replace(',', '.'))
const schema = z.object({
  effective_from: z.iso.date('Укажите дату в формате ГГГГ-ММ-ДД'),
  regime: z.enum(['none', 'usn_income', 'usn_income_expense', 'profit']),
  rate,
  vat_rate: rate,
  income_base: z.enum(['revenue', 'payout'])
})

type Props = {
  workspaceId: string
  storeId: string
  date: string
  onSaved: () => Promise<unknown>
}

export function TaxForm(props: Props) {
  const { user } = useAuth()
  const settings = useQuery({
    queryKey: [
      'user',
      user?.id,
      props.workspaceId,
      props.storeId,
      'finance-tax-settings'
    ],
    queryFn: () => taxSettingsList(props.workspaceId, props.storeId)
  })
  if (settings.isPending) return <Skeleton height={180} />
  if (settings.error)
    return (
      <Notice
        tone='error'
        message={errorMessage(settings.error)}
      />
    )
  const initial = settings.data
    ?.filter(item => item.effective_from <= props.date)
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
}: Props & { initial?: TaxSettingView }) {
  const styles = useStyles()
  const form = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
    defaultValues: {
      effective_from: initial?.effective_from ?? date,
      regime: initial?.regime ?? 'usn_income',
      rate: String(initial?.rate ?? '6'),
      vat_rate: String(initial?.vat_rate ?? '0'),
      income_base: initial?.income_base ?? 'revenue'
    }
  })
  const [regime, incomeBase] = useWatch({
    control: form.control,
    name: ['regime', 'income_base']
  })
  const save = useMutation({
    mutationFn: (values: z.infer<typeof schema>) =>
      taxSettingsSave(workspaceId, storeId, values),
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
      <View style={styles.options}>
        {regimes.map(([key, title]) => (
          <Pressable
            key={key}
            accessibilityRole='radio'
            accessibilityState={{ checked: regime === key }}
            onPress={() => {
              form.setValue('regime', key)
              form.setValue(
                'rate',
                key === 'none'
                  ? '0'
                  : key === 'usn_income'
                    ? '6'
                    : key === 'usn_income_expense'
                      ? '15'
                      : '25'
              )
              if (key === 'none') form.setValue('vat_rate', '0')
            }}
            style={[styles.option, regime === key && styles.selected]}
          >
            <Text
              variant='label'
              tone={regime === key ? 'accent' : 'secondary'}
            >
              {title}
            </Text>
          </Pressable>
        ))}
      </View>
      <FormField
        control={form.control}
        name='rate'
        label='Ставка налога, %'
        keyboardType='decimal-pad'
        editable={regime !== 'none'}
      />
      <FormField
        control={form.control}
        name='vat_rate'
        label='НДС в цене, %'
        keyboardType='decimal-pad'
        editable={regime !== 'none'}
      />
      <Text variant='label'>Налоговая база</Text>
      <View style={styles.options}>
        {(
          [
            ['revenue', 'Выручка от реализации'],
            ['payout', 'Перечисление за товар']
          ] as const
        ).map(([key, title]) => (
          <Pressable
            key={key}
            onPress={() => form.setValue('income_base', key)}
            accessibilityRole='radio'
            accessibilityState={{ checked: incomeBase === key }}
            style={[styles.option, incomeBase === key && styles.selected]}
          >
            <Text variant='label'>{title}</Text>
          </Pressable>
        ))}
      </View>
      <FormField
        control={form.control}
        name='effective_from'
        label='Действует с, ГГГГ-ММ-ДД'
      />
      <Button
        title='Сохранить настройки'
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
