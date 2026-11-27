import { Wallet } from 'lucide-react-native'
import { View } from 'react-native'

import type { DashboardFinance, ProfitReport } from '@app/api'

import { Card, Text } from '@/components/ui'

import { formatMoney } from '@/lib/format'

import { createStyles, useTheme } from '@/theme'

export function ProfitCard({
  report,
  initial,
  currency
}: {
  report?: ProfitReport
  initial?: DashboardFinance
  currency?: string
}) {
  const styles = useStyles()
  const { colors } = useTheme()
  const summary = report?.summary
  const complete = report?.status === 'ready' && summary?.calculation_complete
  const missingCost = (summary?.issues?.missing_cost_units ?? 0) > 0
  const amount = complete
    ? summary.profit_before_tax
    : !report
      ? initial?.profit_before_tax
      : null
  const reason = missingCost
    ? 'Нет себестоимости'
    : report?.is_partial
      ? 'Загрузка отчётов…'
      : report?.status === 'preparing'
        ? 'Считаем…'
        : 'Недостаточно данных'

  return (
    <Card
      tone='accent'
      style={styles.card}
    >
      <View style={styles.row}>
        <View style={styles.icon}>
          <Wallet
            size={22}
            color={colors.accent}
          />
        </View>
        <View style={styles.title}>
          <Text variant='bodyStrong'>Прибыль до налогов</Text>
          <Text
            variant='caption'
            tone='secondary'
          >
            {amount != null ? 'До налогов' : reason}
          </Text>
        </View>
        <Text
          variant='value'
          tabular
        >
          {formatMoney(amount, report?.currency ?? currency)}
        </Text>
      </View>
    </Card>
  )
}

const useStyles = createStyles(({ colors, radius, spacing }) => ({
  card: { gap: spacing.md },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    flexWrap: 'wrap'
  },
  icon: {
    width: 40,
    height: 40,
    borderRadius: radius.control,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.background.card
  },
  title: { flex: 1, minWidth: 130, gap: spacing.xxs }
}))
