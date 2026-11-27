import { View } from 'react-native'

import type { ReplenishmentItem, SupplyCard } from '@app/api'

import { Divider, Text } from '@/components/ui'

import { ProductPhoto } from '@/features/products/components/ProductPhoto'
import { productLabel } from '@/features/products/model/productLabel'
import { useProductDisplay } from '@/features/products/providers/ProductDisplayProvider'

import { formatLongDate, formatNumber, formatUnits } from '@/lib/format'

import { supplyNumber, supplyStatus } from '../model/supplyLabels'

import { createStyles } from '@/theme'

export function ReplenishmentDetails({ item }: { item: ReplenishmentItem }) {
  const styles = useStyles()
  const { mode } = useProductDisplay()
  return (
    <View style={styles.content}>
      <View style={styles.product}>
        <ProductPhoto
          uri={item.photo ?? undefined}
          label={item.title}
          style={styles.photo}
        />
        <View style={styles.name}>
          <Text variant='bodyStrong'>{item.title}</Text>
          <Text
            variant='caption'
            tone='secondary'
          >
            {productLabel(item, mode)}
          </Text>
          {!!item.colors.length && (
            <Text
              variant='caption'
              tone='secondary'
            >
              {item.colors.join(', ')}
            </Text>
          )}
        </View>
      </View>
      <Text
        variant='caption'
        tone='secondary'
      >
        {item.store_name}
      </Text>
      <Value
        label='Рекомендуем довезти'
        value={formatUnits(item.quantity)}
        accent
      />
      <Divider />
      <Value
        label='Остаток FBO'
        value={formatUnits(item.stock)}
      />
      <Value
        label='В оформленных поставках'
        value={formatUnits(item.incoming_quantity)}
      />
      {!!item.incoming_reduction && (
        <Value
          label='Снижение потребности'
          value={formatUnits(item.incoming_reduction)}
        />
      )}
      <Value
        label={
          item.demand_basis === 'ozon_sales'
            ? 'Продаж в день'
            : 'Заказов в день'
        }
        value={formatNumber(item.daily_orders, 1)}
      />
      <Value
        label='Запас сейчас'
        value={`${formatNumber(item.days_of_stock, 1)} дн.`}
      />
      <Value
        label='Целевой запас'
        value='30 дней'
      />
    </View>
  )
}

export function ImportedSupplyDetails({ plan }: { plan: SupplyCard }) {
  const styles = useStyles()
  return (
    <View style={styles.content}>
      <Text variant='sectionTitle'>{supplyNumber(plan)}</Text>
      <Text tone='secondary'>{plan.store_name}</Text>
      <Value
        label='Статус'
        value={supplyStatus(plan)}
        accent
      />
      <Divider />
      <Value
        label='В поставке'
        value={formatUnits(plan.quantity)}
      />
      <Value
        label='Принято'
        value={formatUnits(plan.accepted_quantity)}
      />
      <Value
        label='Отгрузка по плану'
        value={plan.planned_date ? formatLongDate(plan.planned_date) : '—'}
      />
      {plan.actual_date && (
        <Value
          label='Фактическая дата'
          value={formatLongDate(plan.actual_date)}
        />
      )}
      {plan.created_date && (
        <Value
          label='Дата оформления'
          value={formatLongDate(plan.created_date)}
        />
      )}
      <Divider />
      <Text
        variant='caption'
        tone='secondary'
      >
        Склад или кластер
      </Text>
      <Text>{plan.destination || '—'}</Text>
    </View>
  )
}

function Value({
  label,
  value,
  accent = false
}: {
  label: string
  value: string
  accent?: boolean
}) {
  const styles = useStyles()
  return (
    <View style={styles.row}>
      <Text
        variant='label'
        tone='secondary'
        style={styles.name}
      >
        {label}
      </Text>
      <Text
        variant='bodyStrong'
        tabular
        tone={accent ? 'accent' : 'primary'}
        style={styles.value}
      >
        {value}
      </Text>
    </View>
  )
}

const useStyles = createStyles(({ spacing }) => ({
  content: { gap: spacing.md },
  product: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  photo: { width: spacing.xxl * 2, aspectRatio: 3 / 4 },
  name: { flex: 1, minWidth: 0, gap: spacing.xxs },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: spacing.sm
  },
  value: { flexShrink: 1, textAlign: 'right' }
}))
