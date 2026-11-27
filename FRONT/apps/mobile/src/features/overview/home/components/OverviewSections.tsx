import {
  BarChart3,
  Boxes,
  ChevronRight,
  Coins,
  PackageCheck,
  Search,
  ShoppingBag,
  TrendingUp,
  Truck,
  Warehouse
} from 'lucide-react-native'
import type { LucideIcon } from 'lucide-react-native'
import { Pressable, ScrollView, View } from 'react-native'

import { Card, Text } from '@/components/ui'

import { ChannelMetric } from '@/features/inventory/components/InventoryMetrics'
import {
  turnoverLabel,
  turnoverTitle
} from '@/features/inventory/model/stockCover'
import { reportPermission } from '@/features/team/model/permissions'
import { useWorkspace } from '@/features/workspace/providers/WorkspaceProvider'

import { formatMoney, formatNumber, plural } from '@/lib/format'

import type { HomeOverview } from '../hooks/useHomeOverview'

import { SummaryCard, SummaryMetric } from './SummaryCard'
import { createStyles, useTheme } from '@/theme'

export type OverviewTopic =
  'sales' | 'orders' | 'buyouts' | 'funnel' | 'stock' | 'profit'

export function SearchPlaceholder() {
  const styles = useStyles()
  const { colors } = useTheme()
  return (
    <View
      accessible
      accessibilityLabel='Поиск по приложению. Будет доступен позже.'
      style={styles.search}
    >
      <Search
        size={18}
        color={colors.text.secondary}
      />
      <Text
        variant='label'
        tone='secondary'
        style={styles.searchText}
      >
        Поиск по приложению
      </Text>
      <Text
        variant='caption'
        tone='secondary'
      >
        Скоро
      </Text>
    </View>
  )
}

export function CriticalCards({
  overview,
  onSupplies,
  onFinance
}: {
  overview: HomeOverview
  onSupplies: () => void
  onFinance: () => void
}) {
  const styles = useStyles()
  const { can, supports } = useWorkspace()
  const urgent = overview.stock.urgent
  const supplyValue =
    urgent == null
      ? '—'
      : `${formatNumber(urgent)} ${plural(urgent, ['товар', 'товара', 'товаров'])}`
  return (
    <View style={styles.critical}>
      {can('inventory.read') && supports('supplies') && (
        <CriticalCard
          icon={Truck}
          title='Поставки'
          value={supplyValue}
          hint={urgent === 0 ? 'Срочных пополнений нет' : 'Запас FBO до 7 дней'}
          onPress={onSupplies}
        />
      )}
      {can('finance.read') && supports('finance') && (
        <CriticalCard
          icon={Warehouse}
          title='Хранение'
          value={formatMoney(overview.storage, overview.finance?.currency)}
          hint='Расходы за 30 дней'
          onPress={onFinance}
        />
      )}
    </View>
  )
}

function CriticalCard({
  icon: Icon,
  title,
  value,
  hint,
  onPress
}: {
  icon: LucideIcon
  title: string
  value: string
  hint: string
  onPress: () => void
}) {
  const styles = useStyles()
  const { colors } = useTheme()
  return (
    <Pressable
      accessibilityRole='button'
      accessibilityLabel={`${title}: ${value}. ${hint}`}
      onPress={onPress}
      style={({ pressed }) => [styles.criticalItem, pressed && styles.pressed]}
    >
      <Card style={styles.criticalCard}>
        <View style={styles.criticalHeading}>
          <Icon
            size={18}
            color={colors.accent}
          />
          <Text variant='labelStrong'>{title}</Text>
          <ChevronRight
            size={14}
            color={colors.text.secondary}
          />
        </View>
        <Text
          variant='value'
          tabular
          numberOfLines={1}
          adjustsFontSizeToFit
        >
          {value}
        </Text>
        <Text
          variant='caption'
          tone='secondary'
        >
          {hint}
        </Text>
      </Card>
    </Pressable>
  )
}

const SHORTCUTS: { topic: OverviewTopic; label: string; icon: LucideIcon }[] = [
  { topic: 'sales', label: 'Выручка', icon: TrendingUp },
  { topic: 'orders', label: 'Заказы', icon: ShoppingBag },
  { topic: 'buyouts', label: 'Выкупы', icon: PackageCheck },
  { topic: 'funnel', label: 'Воронка', icon: BarChart3 },
  { topic: 'profit', label: 'Прибыль', icon: Coins },
  { topic: 'stock', label: 'Остатки', icon: Boxes }
]

export function AnalyticsShortcuts({
  onOpen
}: {
  onOpen: (topic: OverviewTopic) => void
}) {
  const styles = useStyles()
  const { colors } = useTheme()
  const { can, supports } = useWorkspace()
  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      contentContainerStyle={styles.shortcuts}
    >
      {SHORTCUTS.filter(
        item =>
          can(reportPermission(item.topic)) &&
          supports(
            item.topic === 'stock'
              ? 'inventory'
              : item.topic === 'profit' || item.topic === 'sales'
                ? 'finance_details'
                : 'analytics'
          )
      ).map(({ topic, label, icon: Icon }) => (
        <Pressable
          key={topic}
          accessibilityRole='button'
          accessibilityLabel={label}
          onPress={() => onOpen(topic)}
          style={({ pressed }) => [styles.shortcut, pressed && styles.pressed]}
        >
          <View style={styles.shortcutIcon}>
            <Icon
              size={22}
              color={colors.accent}
            />
          </View>
          <Text
            variant='caption'
            align='center'
          >
            {label}
          </Text>
        </Pressable>
      ))}
    </ScrollView>
  )
}

export function FinanceSummary({
  overview,
  onPress
}: {
  overview: HomeOverview
  onPress: () => void
}) {
  return (
    <SummaryCard
      title='Финансы'
      subtitle='За 30 дней'
      action='Все финансы'
      onPress={onPress}
    >
      <SummaryMetric
        label='Выручка продавца'
        value={formatMoney(
          overview.finance?.totals.seller_revenue,
          overview.finance?.currency
        )}
      />
      <SummaryMetric
        label='Расходы'
        value={formatMoney(overview.expenses, overview.finance?.currency)}
        hint={
          overview.expenses != null && overview.finance?.expenses_exclude_cogs
            ? 'Без себестоимости'
            : undefined
        }
      />
    </SummaryCard>
  )
}

export function StockSummary({
  overview,
  onPress
}: {
  overview: HomeOverview
  onPress: () => void
}) {
  return (
    <SummaryCard
      title='Товары на складах'
      action='Все остатки'
      onPress={onPress}
    >
      <ChannelMetric
        title='FBO'
        data={overview.inventory?.fbo}
        currency={overview.inventory?.currency}
      />
      <ChannelMetric
        title='FBS'
        data={overview.inventory?.fbs}
        currency={overview.inventory?.currency}
      />
      <SummaryMetric
        label='Стоимость остатков'
        value={formatMoney(
          overview.inventory?.total.retail_value,
          overview.inventory?.currency
        )}
      />
      {overview.inventory?.turnover_supported !== false && (
        <SummaryMetric
          label={turnoverTitle(overview.inventory?.turnover_basis)}
          value={turnoverLabel(overview.inventory?.turnover_days)}
        />
      )}
    </SummaryCard>
  )
}

const useStyles = createStyles(({ colors, spacing, radius, sizes }) => ({
  search: {
    minHeight: sizes.control,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    paddingHorizontal: spacing.md,
    backgroundColor: colors.background.card,
    borderRadius: radius.control
  },
  searchText: { flex: 1 },
  critical: { flexDirection: 'row', gap: spacing.sm, alignItems: 'stretch' },
  criticalItem: { flex: 1, minWidth: 0 },
  criticalCard: { flex: 1, gap: spacing.xxs, padding: spacing.md },
  criticalHeading: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xxs,
    flexWrap: 'wrap',
    marginBottom: spacing.xs
  },
  pressed: { opacity: 0.7 },
  shortcuts: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: spacing.xs,
    paddingVertical: spacing.xxs
  },
  shortcut: {
    width: 78,
    alignItems: 'center',
    gap: spacing.xs,
    minHeight: sizes.touchTarget
  },
  shortcutIcon: {
    width: sizes.touchTarget,
    height: sizes.touchTarget,
    borderRadius: radius.control,
    backgroundColor: colors.background.card,
    alignItems: 'center',
    justifyContent: 'center'
  }
}))
