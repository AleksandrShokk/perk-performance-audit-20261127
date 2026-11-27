import { useState } from 'react'
import { Pressable, ScrollView, View } from 'react-native'

import type { ProductItem, ProductModel, ProductVariant } from '@app/api'

import { Button, Text } from '@/components/ui'

import { useWorkspace } from '@/features/workspace/providers/WorkspaceProvider'

import { productId, variantId } from '../model/productIdentity'
import { productOptions, variantLabel } from '../model/productMetrics'

import { ProductGallery } from './ProductGallery'
import { ProductPhoto } from './ProductPhoto'
import { VariantDetails } from './VariantDetails'
import { createStyles } from '@/theme'

export function ProductDetails({
  model,
  workspaceId,
  currency,
  initialArticle,
  initialSize,
  onEdit,
  onGroup
}: {
  model: ProductModel
  workspaceId: string
  currency: string
  initialArticle?: string
  initialSize?: string
  onEdit: (product: ProductItem, variant?: ProductVariant) => void
  onGroup: (product: ProductItem, variant?: ProductVariant) => void
}) {
  const styles = useStyles()
  const { isAdmin } = useWorkspace()
  const [article, setArticle] = useState(
    initialArticle ??
      (model.products[0] ? productId(model.products[0]) : undefined)
  )
  const product =
    model.products.find(item => productId(item) === article) ??
    model.products[0]!
  const [size, setSize] = useState(
    initialSize ??
      (product.variants[0] ? variantId(product.variants[0]) : undefined)
  )
  const variant =
    product.variants.find(item => variantId(item) === size) ??
    product.variants[0]
  const options = productOptions(model.products)
  function select(item: ProductItem) {
    setArticle(productId(item))
    setSize(item.variants[0] ? variantId(item.variants[0]) : undefined)
  }
  return (
    <View style={styles.content}>
      <Text variant='sectionTitle'>{model.title}</Text>
      <ProductGallery
        key={productId(product)}
        photos={product.photos ?? []}
        title={product.title}
      />
      <Text variant='labelStrong'>Вариант</Text>
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.choices}
      >
        {options.map(({ product: item, label }) => (
          <Pressable
            key={productId(item)}
            accessibilityRole='radio'
            accessibilityState={{
              checked: productId(item) === productId(product)
            }}
            accessibilityLabel={`Выбрать ${label}`}
            onPress={() => select(item)}
            style={[
              styles.color,
              productId(item) === productId(product) && styles.selected
            ]}
          >
            <ProductPhoto
              uri={item.photos?.[0]}
              label={item.title}
              style={styles.swatch}
            />
            <Text
              variant='caption'
              numberOfLines={2}
            >
              {label}
            </Text>
          </Pressable>
        ))}
      </ScrollView>
      {(product.variants.length > 1 ||
        product.variants.some(item => item.size && item.size !== '0')) && (
        <>
          <Text variant='labelStrong'>Размер</Text>
          <View style={styles.sizes}>
            {product.variants.map(item => (
              <Pressable
                key={variantId(item)}
                accessibilityRole='radio'
                accessibilityLabel={`Размер ${variantLabel(item.size, item.chrt_id)}`}
                accessibilityState={{
                  checked:
                    variantId(item) ===
                    (variant ? variantId(variant) : undefined)
                }}
                onPress={() => setSize(variantId(item))}
                style={[
                  styles.size,
                  variantId(item) ===
                    (variant ? variantId(variant) : undefined) &&
                    styles.selected
                ]}
              >
                <Text variant='labelStrong'>
                  {variantLabel(item.size, item.chrt_id)}
                </Text>
              </Pressable>
            ))}
          </View>
        </>
      )}
      {product.title !== model.title && (
        <Text variant='bodyStrong'>{product.title}</Text>
      )}
      <VariantDetails
        key={`${productId(product)}:${variant ? variantId(variant) : undefined}`}
        workspaceId={workspaceId}
        product={product}
        selectedVariant={variant}
        currency={currency}
        onEdit={selected => onEdit(product, selected)}
      />
      {isAdmin && product.marketplace === 'wildberries' && (
        <Button
          title='Настроить объединение'
          variant='ghost'
          onPress={() => onGroup(product, variant)}
        />
      )}
    </View>
  )
}

const useStyles = createStyles(({ colors, spacing, radius, sizes }) => ({
  content: { gap: spacing.md },
  choices: { gap: spacing.sm },
  color: {
    width: spacing.xxl * 3,
    padding: spacing.xs,
    gap: spacing.xs,
    borderRadius: radius.control,
    borderWidth: 1,
    borderColor: colors.border
  },
  swatch: { width: '100%', aspectRatio: 1 },
  selected: { backgroundColor: colors.accentSoft, borderColor: colors.accent },
  sizes: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs },
  size: {
    minWidth: sizes.touchTarget,
    minHeight: sizes.touchTarget,
    paddingHorizontal: spacing.md,
    justifyContent: 'center',
    alignItems: 'center',
    borderRadius: radius.control,
    borderWidth: 1,
    borderColor: colors.border
  }
}))
