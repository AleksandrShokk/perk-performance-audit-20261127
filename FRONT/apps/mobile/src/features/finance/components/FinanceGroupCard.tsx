import { financeLineShare } from '@app/analytics/finance'
import { ChevronDown, ChevronUp } from 'lucide-react-native'
import { Pressable, View } from 'react-native'

import type { FinanceGroup, FinanceLine } from '@app/api'

import { Card, Divider, Text } from '@/components/ui'

import { formatNumber, formatPercent } from '@/lib/format'

import { formatFinanceMoney } from '../model/financeFormat'

import { createStyles, useTheme } from '@/theme'

export function FinanceGroupCard({
  group,
  currency,
  revenue,
  expanded,
  onPress
}: {
  group: FinanceGroup
  currency: string
  revenue: string | null
  expanded: boolean
  onPress: () => void
}) {
  const styles = useStyles()
  const { colors } = useTheme()
  const Chevron = expanded ? ChevronUp : ChevronDown
  return (
    <Card>
      <Pressable
        style={styles.heading}
        onPress={onPress}
        accessibilityRole='button'
        accessibilityLabel={group.title}
        accessibilityState={{ expanded }}
      >
        <View style={styles.name}>
          <Text variant='bodyStrong'>{group.title}</Text>
          {group.share_percent != null && (
            <Text
              variant='caption'
              tone='secondary'
            >
              {formatPercent(group.share_percent)} от выручки
            </Text>
          )}
        </View>
        <Text
          variant='bodyStrong'
          tabular
        >
          {formatFinanceMoney(group.amount, currency)}
        </Text>
        <Chevron
          size={18}
          color={colors.text.secondary}
        />
      </Pressable>
      {expanded && (
        <View style={styles.details}>
          <Divider />
          {group.lines.map(item => (
            <FinanceLineRow
              key={item.key}
              item={item}
              currency={currency}
              revenue={revenue}
            />
          ))}
        </View>
      )}
    </Card>
  )
}

function FinanceLineRow({
  item,
  currency,
  revenue
}: {
  item: FinanceLine
  currency: string
  revenue: string | null
}) {
  const styles = useStyles()
  const share = financeLineShare(item, revenue)
  const value =
    item.unit === 'units'
      ? `${formatNumber(item.amount)}${item.amount == null ? '' : ' шт.'}`
      : item.unit === 'percent'
        ? formatPercent(item.amount)
        : formatFinanceMoney(item.amount, currency)
  return (
    <View style={styles.line}>
      <View style={styles.name}>
        <Text variant='label'>{item.title}</Text>
      </View>
      <View style={styles.value}>
        <Text
          variant='labelStrong'
          tabular
        >
          {value}
        </Text>
        {share != null && (
          <Text
            variant='caption'
            tone='secondary'
            tabular
          >
            {formatPercent(share)}
          </Text>
        )}
      </View>
    </View>
  )
}

const useStyles = createStyles(({ spacing }) => ({
  heading: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    minHeight: 48
  },
  name: { flex: 1, gap: spacing.xxs },
  value: { alignItems: 'flex-end', gap: spacing.xxs },
  details: { gap: spacing.md, marginTop: spacing.sm },
  line: { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.md }
}))
