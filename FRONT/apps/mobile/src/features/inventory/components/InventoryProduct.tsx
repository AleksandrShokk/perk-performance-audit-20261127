import { ChevronRight } from 'lucide-react-native'
import { Pressable, View } from 'react-native'

import type { InventoryPosition } from '@app/api'

import { Card, Divider, Text } from '@/components/ui'

import { ProductGallery } from '@/features/products/components/ProductGallery'
import { ProductPhoto } from '@/features/products/components/ProductPhoto'
import { variantId } from '@/features/products/model/productIdentity'
import { productLabel } from '@/features/products/model/productLabel'
import { variantLabel } from '@/features/products/model/productMetrics'
import { useProductDisplay } from '@/features/products/providers/ProductDisplayProvider'

import { formatUnits } from '@/lib/format'

import { turnoverLabel, turnoverTitle } from '../model/stockCover'

import { ChannelMetric } from './InventoryMetrics'
import { createStyles, useTheme } from '@/theme'

function useIdentity(position: InventoryPosition) {
  const { mode } = useProductDisplay()
  const product = position.product
  return productLabel(
    { ...product, barcodes: product.variants.flatMap(item => item.barcodes) },
    mode
  )
}

export function InventoryProduct({
  position,
  allStores,
  onPress
}: {
  position: InventoryPosition
  allStores: boolean
  onPress: () => void
}) {
  const styles = useStyles()
  const { colors } = useTheme()
  const product = position.product
  const label = useIdentity(position)
  return (
    <Card>
      <Pressable
        style={styles.content}
        accessibilityRole='button'
        accessibilityLabel={`Остатки ${product.title}`}
        onPress={onPress}
      >
        <View style={styles.row}>
          <ProductPhoto
            uri={product.photos?.[0]}
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
              numberOfLines={1}
            >
              {label}
            </Text>
            {!!product.colors.length && (
              <Text
                variant='caption'
                tone='secondary'
                numberOfLines={1}
              >
                {product.colors.join(', ')}
              </Text>
            )}
          </View>
          <ChevronRight
            size={18}
            color={colors.text.secondary}
          />
        </View>
        <View style={styles.row}>
          <View style={styles.name}>
            <Text
              variant='caption'
              tone='secondary'
            >
              FBO
            </Text>
            <Text
              variant='bodyStrong'
              tabular
            >
              {formatUnits(position.fbo.units)}
            </Text>
          </View>
          <View style={styles.name}>
            <Text
              variant='caption'
              tone='secondary'
            >
              FBS
            </Text>
            <Text
              variant='bodyStrong'
              tabular
            >
              {formatUnits(position.fbs.units)}
            </Text>
          </View>
        </View>
        <View style={styles.between}>
          <Text
            variant='caption'
            tone='secondary'
          >
            {turnoverTitle(position.turnover_basis)}
          </Text>
          <Text
            variant='labelStrong'
            style={styles.coverValue}
            tabular
          >
            {turnoverLabel(position.turnover_days, position.turnover_status)}
          </Text>
        </View>
      </Pressable>
    </Card>
  )
}

export function InventoryDetails({
  position,
  currency,
  canCost = false
}: {
  position: InventoryPosition
  currency?: string
  canCost?: boolean
}) {
  const styles = useStyles()
  const product = position.product
  const label = useIdentity(position)
  return (
    <View style={styles.content}>
      <Text variant='sectionTitle'>{product.title}</Text>
      <ProductGallery
        photos={product.photos ?? []}
        title={product.title}
      />
      <Text
        variant='label'
        tone='secondary'
      >
        {label}
        {product.colors.length ? ` · ${product.colors.join(', ')}` : ''}
      </Text>
      <View style={styles.row}>
        <ChannelMetric
          title='FBO'
          data={position.fbo}
          currency={currency}
          showCost={canCost}
        />
        <ChannelMetric
          title='FBS'
          data={position.fbs}
          currency={currency}
          showCost={canCost}
        />
      </View>
      <View style={styles.between}>
        <Text variant='label'>{turnoverTitle(position.turnover_basis)}</Text>
        <Text
          variant='bodyStrong'
          style={styles.coverValue}
        >
          {turnoverLabel(position.turnover_days, position.turnover_status)}
        </Text>
      </View>
      {product.variants.map(item => {
        const fbs = position.fbs_sizes?.find(
          row =>
            (row.variant_id || row.chrt_id) ===
            (row.variant_id ? variantId(item) : item.chrt_id)
        )
        const fbsUnits =
          position.fbs.units == null ? null : (fbs?.quantity ?? 0)
        return (
          <View
            key={variantId(item)}
            style={styles.variant}
          >
            <Text variant='bodyStrong'>
              {variantLabel(item.size, item.chrt_id)}
            </Text>
            <View style={styles.between}>
              <Text
                variant='label'
                tone='secondary'
              >
                FBO
              </Text>
              <Text variant='bodyStrong'>{formatUnits(item.stock)}</Text>
            </View>
            {item.warehouses.map(row => (
              <View
                key={row.name}
                style={styles.between}
              >
                <Text
                  variant='caption'
                  style={styles.name}
                >
                  {row.name || 'Склад не указан'}
                </Text>
                <Text variant='labelStrong'>{formatUnits(row.quantity)}</Text>
              </View>
            ))}
            <Divider />
            <View style={styles.between}>
              <Text
                variant='label'
                tone='secondary'
              >
                FBS
              </Text>
              <Text variant='bodyStrong'>{formatUnits(fbsUnits)}</Text>
            </View>
            {Object.entries(fbs?.warehouses ?? {}).map(([name, quantity]) => (
              <View
                key={name}
                style={styles.between}
              >
                <Text
                  variant='caption'
                  style={styles.name}
                >
                  {name || 'Склад продавца'}
                </Text>
                <Text variant='labelStrong'>{formatUnits(quantity)}</Text>
              </View>
            ))}
            {!!item.barcodes.length && (
              <Text
                selectable
                variant='caption'
                tone='secondary'
              >
                {item.barcodes.join(' · ')}
              </Text>
            )}
          </View>
        )
      })}
    </View>
  )
}

const useStyles = createStyles(({ colors, spacing, radius }) => ({
  content: { gap: spacing.md },
  row: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  between: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: spacing.sm
  },
  coverValue: { flexShrink: 1, textAlign: 'right' },
  name: { flex: 1, minWidth: 0, gap: spacing.xxs },
  photo: { width: spacing.xxl * 2, aspectRatio: 3 / 4 },
  variant: {
    gap: spacing.sm,
    padding: spacing.md,
    borderRadius: radius.control,
    backgroundColor: colors.background.screen
  }
}))
