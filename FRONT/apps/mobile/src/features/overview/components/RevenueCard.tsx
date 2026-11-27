import { View } from 'react-native'

import type { ProfitReport } from '@app/api'

import {
  Card,
  Divider,
  InfoHint,
  SegmentedControl,
  Skeleton,
  Text
} from '@/components/ui'

import type { DateRange } from '@/lib/dates'
import { formatDateRange, formatNumber, moneyParts } from '@/lib/format'

import { useChartGrouping } from '../hooks/useChartGrouping'
import { type ChartGrouping, chartPoints } from '../model/chartPoints'

import { RevenueChart } from './RevenueChart'
import { createStyles } from '@/theme'

const GROUPINGS: { value: ChartGrouping; label: string }[] = [
  { value: 'day', label: 'Дни' },
  { value: 'week', label: 'Недели' },
  { value: 'month', label: 'Месяцы' }
]

type Props = {
  report?: ProfitReport
  range: DateRange
  initialRevenue?: string | null
  initialCurrency?: string
}

export function RevenueCard({
  report,
  range,
  initialRevenue,
  initialCurrency
}: Props) {
  const styles = useStyles()
  const [grouping, setGrouping] = useChartGrouping()
  const ready = report?.status === 'ready'
  const money = moneyParts(
    ready ? report.summary?.revenue : initialRevenue,
    report?.currency ?? initialCurrency
  )

  return (
    <Card tone='accent'>
      <View style={styles.heading}>
        <Text tone='secondary'>Выручка</Text>
        <InfoHint
          title='Выручка'
          message={
            report?.is_partial || report?.period_covered === false
              ? 'Выручка по загруженной части финансовых отчётов. Итог обновляется по мере поступления данных.'
              : 'Выручка по финансовым отчётам за выбранный период.'
          }
        />
      </View>
      <View style={styles.amount}>
        {!report && initialRevenue === undefined ? (
          <Skeleton
            width='75%'
            height={42}
          />
        ) : (
          <>
            <Text
              variant='mainValue'
              tabular
            >
              {money.amount}
            </Text>
            <Text
              variant='value'
              tone='secondary'
            >
              {money.symbol}
            </Text>
          </>
        )}
      </View>
      <Text
        variant='caption'
        tone='secondary'
      >
        {formatDateRange(range.date_from, range.date_to)}
      </Text>
      {!report ? (
        <Skeleton
          height={178}
          style={styles.skeleton}
        />
      ) : ready ? (
        <View style={styles.chart}>
          <SegmentedControl
            options={GROUPINGS}
            value={grouping}
            onChange={setGrouping}
          />
          <RevenueChart
            key={`${grouping}:${range.date_from}:${range.date_to}`}
            points={chartPoints(report, range, grouping)}
            currency={report.currency}
            grouping={grouping}
          />
        </View>
      ) : (
        <View style={styles.waiting}>
          <Text tone='secondary'>
            {report.status === 'preparing'
              ? 'Готовим финансовый отчёт'
              : 'За этот период данных пока нет'}
          </Text>
        </View>
      )}
      <Divider />
      <View style={styles.metrics}>
        <View style={styles.metric}>
          <Text
            variant='label'
            tone='secondary'
          >
            Продажи
          </Text>
          <Text
            variant='value'
            tabular
          >
            {ready ? formatNumber(report.summary?.sales ?? 0) : '—'}{' '}
            <Text
              variant='caption'
              tone='secondary'
            >
              шт.
            </Text>
          </Text>
        </View>
        <View style={styles.metric}>
          <Text
            variant='label'
            tone='secondary'
          >
            Возвраты
          </Text>
          <Text
            variant='value'
            tabular
          >
            {ready ? formatNumber(report.summary?.returns ?? 0) : '—'}{' '}
            <Text
              variant='caption'
              tone='secondary'
            >
              шт.
            </Text>
          </Text>
        </View>
      </View>
    </Card>
  )
}

const useStyles = createStyles(({ spacing }) => ({
  heading: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between'
  },
  amount: {
    flexDirection: 'row',
    alignItems: 'baseline',
    gap: spacing.xs,
    marginTop: spacing.md,
    marginBottom: spacing.xs
  },
  skeleton: { marginVertical: spacing.lg },
  chart: { marginTop: spacing.lg },
  waiting: { minHeight: 178, justifyContent: 'center', gap: spacing.xs },
  metrics: {
    flexDirection: 'row',
    gap: spacing.xxxl,
    paddingVertical: spacing.md
  },
  metric: { gap: spacing.xs }
}))
