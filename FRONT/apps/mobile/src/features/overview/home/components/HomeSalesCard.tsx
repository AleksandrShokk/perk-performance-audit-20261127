import {
  ArrowDownRight,
  ArrowUpRight,
  SlidersHorizontal
} from 'lucide-react-native'
import { type ReactNode, useState } from 'react'
import { ActivityIndicator, Pressable, View } from 'react-native'

import { Button, Card, Skeleton, Text } from '@/components/ui'

import { formatDateRange, formatPercent } from '@/lib/format'

import { BuyoutHint } from '../../components/BuyoutHint'
import type { HomeOverview } from '../hooks/useHomeOverview'
import { formatOrderValue } from '../model/overviewMetrics'
import { HOME_PERIODS, type HomeFilters } from '../model/overviewTypes'

import { OrdersBarChart } from './OrdersBarChart'
import { SalesFiltersSheet } from './SalesFiltersSheet'
import { createStyles, useTheme } from '@/theme'

export function HomeSalesCard({
  overview,
  filters,
  onChange
}: {
  overview: HomeOverview
  filters: HomeFilters
  onChange: (value: HomeFilters) => void
}) {
  const styles = useStyles()
  const { colors } = useTheme()
  const [filtersOpen, setFiltersOpen] = useState(false)
  const { sales, range } = overview
  const periodLabel =
    typeof filters.period === 'object'
      ? formatDateRange(range.date_from, range.date_to)
      : HOME_PERIODS.find(option => option.value === filters.period)?.label
  return (
    <Card>
      <View style={styles.heading}>
        <Text variant='sectionTitle'>Заказано товаров</Text>
        <Pressable
          accessibilityRole='button'
          accessibilityLabel='Фильтры графика'
          onPress={() => setFiltersOpen(true)}
          style={styles.filter}
        >
          <SlidersHorizontal
            size={14}
            color={colors.text.secondary}
          />
          <Text variant='labelStrong'>{periodLabel}</Text>
        </Pressable>
      </View>

      <View style={styles.figures}>
        <SalesFigure
          label='Заказано'
          value={`${formatOrderValue(sales.ordered, filters.unit, sales.currency)}`}
          change={sales.orderedChange}
        />
        <SalesFigure
          label='Выкуплено'
          value={`${formatOrderValue(sales.buyouts, filters.unit, sales.currency)}`}
          change={sales.buyoutsChange}
          hint={<BuyoutHint />}
        />
      </View>

      {overview.salesPending ? (
        <Skeleton height={220} />
      ) : !overview.salesHasData ? (
        <Text
          tone='secondary'
          style={styles.unavailable}
        >
          {overview.salesLoading ? 'Загружаем график…' : 'Данных пока нет'}
        </Text>
      ) : sales.amountsUnavailable ? (
        <View style={styles.unavailable}>
          <Text
            variant='label'
            tone='secondary'
          >
            Разные валюты. Выберите один магазин.
          </Text>
          <Button
            title='Показать в штуках'
            variant='secondary'
            onPress={() => onChange({ ...filters, unit: 'units' })}
          />
        </View>
      ) : (
        <OrdersBarChart
          key={`${overview.scope}:${range.date_from}:${range.date_to}:${filters.unit}:${filters.comparison}`}
          points={sales.points}
          comparison={filters.comparison}
          unit={filters.unit}
          currency={sales.currency}
        />
      )}

      {(overview.salesLoading || overview.summaryLoading) && (
        <View style={styles.loading}>
          <ActivityIndicator
            size='small'
            color={colors.accent}
          />
          <Text
            variant='caption'
            tone='secondary'
            style={styles.loadingText}
          >
            {overview.salesLoading
              ? `Загружено ${sales.knownDays} из ${sales.points.length} дней`
              : 'Обновляем итоги периода…'}
          </Text>
        </View>
      )}
      {overview.summaryError && (
        <Text
          variant='caption'
          tone='secondary'
        >
          Итоги не обновлены
        </Text>
      )}

      {filtersOpen && (
        <SalesFiltersSheet
          value={filters}
          onClose={() => setFiltersOpen(false)}
          onApply={value => {
            onChange(value)
            setFiltersOpen(false)
          }}
        />
      )}
    </Card>
  )
}

function SalesFigure({
  label,
  value,
  change,
  hint
}: {
  label: string
  value: string
  change: string | null
  hint?: ReactNode
}) {
  const styles = useStyles()
  const positive = change != null && Number(change) >= 0
  const Arrow = positive ? ArrowUpRight : ArrowDownRight
  const { colors } = useTheme()
  return (
    <View style={styles.figure}>
      <View style={styles.figureHeading}>
        <Text
          variant='label'
          tone='secondary'
          numberOfLines={1}
          style={styles.figureLabel}
        >
          {label}
        </Text>
        {hint}
      </View>
      <Text
        variant='value'
        tabular
        numberOfLines={1}
        adjustsFontSizeToFit
      >
        {value}
      </Text>
      <View style={styles.change}>
        {change != null && (
          <Arrow
            size={14}
            color={positive ? colors.success : colors.error}
          />
        )}
        <Text
          variant='caption'
          tone={change == null ? 'secondary' : positive ? 'success' : 'error'}
        >
          {formatPercent(change, { signed: true })}
        </Text>
      </View>
    </View>
  )
}

const useStyles = createStyles(({ colors, spacing, radius, sizes }) => ({
  heading: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    flexWrap: 'wrap',
    gap: spacing.xs
  },
  filter: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xxs,
    minHeight: 30,
    borderRadius: radius.control,
    backgroundColor: colors.background.screen,
    paddingHorizontal: spacing.xs
  },
  figures: { flexDirection: 'row', gap: spacing.lg },
  figure: { flex: 1, minWidth: 0, gap: spacing.xxs },
  figureHeading: {
    minHeight: sizes.touchTarget,
    flexDirection: 'row',
    alignItems: 'center'
  },
  figureLabel: { flexShrink: 1 },
  change: { flexDirection: 'row', alignItems: 'center', gap: spacing.xxs },
  meta: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: spacing.xs,
    flexWrap: 'wrap',
    marginTop: spacing.xs,
    marginBottom: spacing.md
  },
  loading: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginTop: spacing.md
  },
  loadingText: { flex: 1 },
  note: { marginTop: spacing.md },
  unavailable: { gap: spacing.md, paddingVertical: spacing.lg }
}))
