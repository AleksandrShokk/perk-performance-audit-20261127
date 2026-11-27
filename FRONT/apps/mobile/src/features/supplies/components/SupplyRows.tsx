import { ChevronRight } from 'lucide-react-native'
import { Pressable, View } from 'react-native'

import type { ReplenishmentItem, SupplyCard } from '@app/api'

import { Text } from '@/components/ui'

import { ProductPhoto } from '@/features/products/components/ProductPhoto'
import { productLabel } from '@/features/products/model/productLabel'
import { useProductDisplay } from '@/features/products/providers/ProductDisplayProvider'

import { formatLongDate, formatNumber, formatUnits } from '@/lib/format'

import { supplyNumber, supplyStatus } from '../model/supplyLabels'

import { createStyles, useTheme } from '@/theme'

export function ReplenishmentRow({
  item,
  allStores,
  onPress
}: {
  item: ReplenishmentItem
  allStores: boolean
  onPress: () => void
}) {
  const styles = useStyles()
  const { colors } = useTheme()
  const { mode } = useProductDisplay()
  return (
    <Pressable
      style={styles.product}
      accessibilityRole='button'
      accessibilityLabel={`Рекомендация: ${item.title}`}
      onPress={onPress}
    >
      <ProductPhoto
        uri={item.photo ?? undefined}
        label={item.title}
        style={styles.photo}
      />
      <View style={styles.name}>
        {allStores && (
          <Text
            variant='caption'
            tone='secondary'
          >
            {item.store_name}
          </Text>
        )}
        <Text
          variant='labelStrong'
          numberOfLines={2}
        >
          {item.title}
        </Text>
        <Text
          variant='caption'
          tone='secondary'
          numberOfLines={1}
        >
          {productLabel(item, mode)}
        </Text>
        <Text
          variant='caption'
          tone={item.urgent ? 'accent' : 'secondary'}
        >
          {item.stock === 0
            ? 'Нет на FBO'
            : `Запас ${formatNumber(item.days_of_stock, 1)} дн.`}
        </Text>
      </View>
      <View style={styles.quantity}>
        <Text
          variant='bodyStrong'
          tabular
        >
          {formatUnits(item.quantity)}
        </Text>
        <Text
          variant='caption'
          tone='secondary'
        >
          довезти
        </Text>
      </View>
      <ChevronRight
        size={18}
        color={colors.text.secondary}
      />
    </Pressable>
  )
}

export function SupplyRow({
  plan,
  allStores,
  onPress
}: {
  plan: SupplyCard
  allStores: boolean
  onPress: () => void
}) {
  const styles = useStyles()
  const { colors } = useTheme()
  return (
    <Pressable
      style={styles.plan}
      accessibilityRole='button'
      accessibilityLabel={`Открыть ${supplyNumber(plan)}`}
      onPress={onPress}
    >
      <View style={styles.between}>
        <Text
          variant='bodyStrong'
          style={styles.grow}
        >
          {supplyNumber(plan)}
        </Text>
        <Text
          variant='labelStrong'
          tabular
        >
          {formatUnits(plan.quantity)}
        </Text>
        <ChevronRight
          size={18}
          color={colors.text.secondary}
        />
      </View>
      {allStores && (
        <Text
          variant='caption'
          tone='secondary'
        >
          {plan.store_name}
        </Text>
      )}
      <Text
        variant='label'
        tone='secondary'
      >
        {plan.destination || 'Склад не указан'}
      </Text>
      <View style={styles.between}>
        <Text
          variant='caption'
          tone={plan.rejected ? 'error' : 'accent'}
          style={styles.grow}
        >
          {supplyStatus(plan)}
        </Text>
        {plan.planned_date && (
          <Text
            variant='caption'
            tone='secondary'
          >
            {formatLongDate(plan.planned_date)}
          </Text>
        )}
      </View>
      {plan.status === 'accepted' && plan.accepted_quantity != null && (
        <Text
          variant='caption'
          tone='secondary'
        >
          Принято {formatUnits(plan.accepted_quantity)}
        </Text>
      )}
    </Pressable>
  )
}

const useStyles = createStyles(({ spacing }) => ({
  product: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  name: { flex: 1, minWidth: 0, gap: spacing.xxs },
  grow: { flex: 1, minWidth: 0 },
  quantity: { alignItems: 'flex-end', gap: spacing.xxs, flexShrink: 1 },
  photo: { width: spacing.xxl, aspectRatio: 3 / 4 },
  plan: { gap: spacing.xs },
  between: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: spacing.sm
  }
}))
