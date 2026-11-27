import { Decimal } from 'decimal.js'
import { Package } from 'lucide-react-native'
import { Fragment } from 'react'
import { View } from 'react-native'

import type { ProfitReport } from '@app/api'

import { Divider, InfoHint, ListRow, Text } from '@/components/ui'

import { ProductDisplaySelect } from '@/features/products/components/ProductDisplaySelect'
import { productLabel } from '@/features/products/model/productLabel'
import { useProductDisplay } from '@/features/products/providers/ProductDisplayProvider'

import { formatMoney, formatUnits } from '@/lib/format'

import { createStyles } from '@/theme'

export function SalesLeaders({ report }: { report?: ProfitReport }) {
  const styles = useStyles()
  const { mode } = useProductDisplay()
  const products = [...(report?.products ?? [])]
    .filter(product => product.revenue != null)
    .sort((a, b) => new Decimal(b.revenue ?? 0).comparedTo(a.revenue ?? 0))
    .slice(0, 5)

  if (!products.length) return null
  return (
    <View>
      <View style={styles.heading}>
        <Text variant='sectionTitle'>Лидеры продаж</Text>
        <ProductDisplaySelect />
      </View>
      {products.map((product, index) => (
        <Fragment key={product.id || product.nm_id}>
          {index > 0 && <Divider />}
          <ListRow
            icon={Package}
            title={productLabel(product, mode)}
            subtitle={formatUnits(product.sales)}
            trailing={
              <View style={styles.amount}>
                {mode === 'barcode' && (product.barcodes?.length ?? 0) > 1 && (
                  <InfoHint
                    title='Штрихкоды товара'
                    message={product.barcodes!.join('\n')}
                  />
                )}
                <Text
                  variant='labelStrong'
                  tabular
                >
                  {formatMoney(product.revenue, report?.currency)}
                </Text>
              </View>
            }
          />
        </Fragment>
      ))}
    </View>
  )
}

const useStyles = createStyles(({ spacing }) => ({
  heading: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: spacing.sm,
    flexWrap: 'wrap'
  },
  amount: { flexDirection: 'row', alignItems: 'center', gap: spacing.xxs }
}))
