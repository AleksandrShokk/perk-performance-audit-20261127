import { View } from 'react-native'

import type { InventoryAmounts, InventoryOverview } from '@app/api'

import { Card, Divider, Text } from '@/components/ui'

import { formatMoney, formatUnits } from '@/lib/format'

import { turnoverLabel, turnoverTitle } from '../model/stockCover'

import { createStyles } from '@/theme'

export function ChannelMetric({
  title,
  data,
  currency,
  showCost = false
}: {
  title: string
  data?: InventoryAmounts
  currency?: string
  showCost?: boolean
}) {
  const styles = useStyles()
  return (
    <View style={styles.metric}>
      <Text variant='bodyStrong'>{title}</Text>
      <Text
        variant='sectionTitle'
        tabular
        numberOfLines={1}
        adjustsFontSizeToFit
      >
        {formatMoney(data?.retail_value, currency)}
      </Text>
      <Text
        variant='label'
        tone='secondary'
      >
        {formatUnits(data?.units)}
      </Text>
      {showCost && (
        <>
          <Divider />
          <Text
            variant='caption'
            tone='secondary'
          >
            Себестоимость
          </Text>
          <Text
            variant='bodyStrong'
            tabular
            numberOfLines={1}
            adjustsFontSizeToFit
          >
            {formatMoney(data?.cost_value, currency)}
          </Text>
        </>
      )}
    </View>
  )
}

export function InventoryTotals({ data }: { data: InventoryOverview }) {
  const styles = useStyles()
  return (
    <View style={styles.sections}>
      <View style={styles.row}>
        {(['fbo', 'fbs'] as const).map(channel => (
          <Card
            key={channel}
            style={styles.card}
          >
            <ChannelMetric
              title={channel.toUpperCase()}
              data={data[channel]}
              currency={data.currency}
              showCost={data.can_cost}
            />
          </Card>
        ))}
      </View>
      {data.turnover_supported !== false && (
        <Card style={styles.metric}>
          <Text
            variant='label'
            tone='secondary'
          >
            {turnoverTitle(data.turnover_basis)}
          </Text>
          <Text
            variant='value'
            tabular
          >
            {data.turnover_days == null && data.turnover_loading
              ? 'Загружаем…'
              : turnoverLabel(data.turnover_days)}
          </Text>
        </Card>
      )}
    </View>
  )
}

const useStyles = createStyles(({ spacing }) => ({
  sections: { gap: spacing.sm },
  row: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  card: { flex: 1, minWidth: 130 },
  metric: { flex: 1, minWidth: 110, gap: spacing.sm }
}))
