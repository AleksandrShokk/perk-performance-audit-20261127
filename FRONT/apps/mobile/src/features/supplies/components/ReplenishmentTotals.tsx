import { View } from 'react-native'

import type { ReplenishmentOverview } from '@app/api'

import { Card, Text } from '@/components/ui'

import { formatNumber, formatUnits, plural } from '@/lib/format'

import { createStyles } from '@/theme'

export function ReplenishmentTotals({
  data,
  allStores
}: {
  data?: ReplenishmentOverview
  allStores: boolean
}) {
  const styles = useStyles()
  return (
    <Card style={styles.totals}>
      <View style={styles.metric}>
        <Text
          variant='value'
          tabular
          numberOfLines={1}
          adjustsFontSizeToFit
        >
          {formatUnits(data?.recommended_units)}
        </Text>
        <Text
          variant='caption'
          tone='secondary'
        >
          {allStores ? 'Всего к пополнению · FBO' : 'К пополнению · FBO'}
        </Text>
      </View>
      <View style={styles.metric}>
        <Text
          variant='value'
          tabular
          numberOfLines={1}
          adjustsFontSizeToFit
        >
          {formatNumber(data?.product_count)}
        </Text>
        <Text
          variant='caption'
          tone='secondary'
        >
          {plural(data?.product_count ?? 0, ['позиция', 'позиции', 'позиций'])}
        </Text>
      </View>
    </Card>
  )
}

const useStyles = createStyles(({ spacing }) => ({
  totals: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.md },
  metric: { flex: 1, minWidth: 110, gap: spacing.xs }
}))
