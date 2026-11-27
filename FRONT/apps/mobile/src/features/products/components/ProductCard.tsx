import { ChevronRight } from 'lucide-react-native'
import { Pressable, View } from 'react-native'

import type { ProductModel } from '@app/api'

import { Card, Pill, Text } from '@/components/ui'

import { formatUnits, plural } from '@/lib/format'

import { modelCostLabel, modelIdentity } from '../model/productMetrics'
import { useProductDisplay } from '../providers/ProductDisplayProvider'

import { ProductPhoto } from './ProductPhoto'
import { createStyles, useTheme } from '@/theme'

export function ProductCard({
  product,
  currency,
  allStores,
  canCost,
  canStock,
  onPress
}: {
  product: ProductModel
  currency: string
  allStores: boolean
  canCost: boolean
  canStock: boolean
  onPress: () => void
}) {
  const styles = useStyles()
  const { colors } = useTheme()
  const { mode } = useProductDisplay()
  const variants = product.products.reduce(
    (sum, item) => sum + item.variants.length,
    0
  )
  const colorNames = [...new Set(product.products.flatMap(item => item.colors))]
  return (
    <Card>
      <Pressable
        accessibilityRole='button'
        accessibilityLabel={`Товар ${product.title}`}
        onPress={onPress}
        style={styles.content}
      >
        <View style={styles.row}>
          <ProductPhoto
            uri={product.products.flatMap(item => item.photos ?? [])[0]}
            label={product.title}
            style={styles.photo}
          />
          <View style={styles.name}>
            {allStores && (
              <Text
                variant='caption'
                tone='secondary'
              >
                {product.store_name}
              </Text>
            )}
            <Text
              variant='bodyStrong'
              numberOfLines={2}
            >
              {product.title}
            </Text>
            <Text
              variant='caption'
              tone='secondary'
              numberOfLines={2}
            >
              {modelIdentity(product, mode)}
            </Text>
            {!!colorNames.length && (
              <Text
                variant='caption'
                tone='secondary'
                numberOfLines={2}
              >
                {colorNames.join(' · ')}
              </Text>
            )}
          </View>
          <ChevronRight
            size={18}
            color={colors.text.secondary}
          />
        </View>
        <View style={styles.between}>
          <Text
            variant='label'
            tone='secondary'
          >
            {variants} {plural(variants, ['вариант', 'варианта', 'вариантов'])}
          </Text>
          {canStock && (
            <Text variant='bodyStrong'>FBO · {formatUnits(product.stock)}</Text>
          )}
        </View>
        {canCost && (
          <View style={styles.between}>
            <Text
              variant='label'
              tone='secondary'
            >
              Себестоимость
            </Text>
            <Text variant='labelStrong'>
              {modelCostLabel(product, currency)}
            </Text>
          </View>
        )}
        {!!product.missing_cost_variants && (
          <Pill
            label={`Без цены: ${product.missing_cost_variants}`}
            tone='accent'
          />
        )}
      </Pressable>
    </Card>
  )
}
const useStyles = createStyles(({ spacing }) => ({
  content: { gap: spacing.sm },
  row: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  between: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: spacing.sm
  },
  name: { flex: 1, gap: spacing.xs },
  photo: { width: spacing.xxl * 2.5, aspectRatio: 3 / 4 }
}))
