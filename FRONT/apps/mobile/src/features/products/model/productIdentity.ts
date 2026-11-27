import type { ProductItem, ProductVariant } from '@app/api'

// The legacy fallback also supports older persisted WB reports during an app update.
export const productId = (product: Pick<ProductItem, 'id' | 'nm_id'>) =>
  product.id || product.nm_id
export const variantId = (variant: Pick<ProductVariant, 'id' | 'chrt_id'>) =>
  variant.id || variant.chrt_id
