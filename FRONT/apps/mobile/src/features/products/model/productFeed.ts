import type { ProductItem, ProductModel } from '@app/api'

import { productId } from './productIdentity'

export type ProductFeedItem = {
  card: ProductModel
  group: ProductModel
  selectedProduct?: ProductItem
}

/** В ленте можно раскрыть артикулы; при открытии сохраняем всю исходную карточку. */
export function productFeed(
  cards: ProductModel[],
  showAllVariants: boolean
): ProductFeedItem[] {
  return cards.flatMap(group =>
    showAllVariants
      ? group.products.map(product => ({
          group,
          selectedProduct: product,
          card: {
            ...group,
            id: `${group.id}:article:${productId(product)}`,
            title: product.title,
            brand: product.brand,
            products: [product],
            stock: product.stock,
            missing_cost_variants: product.missing_cost_variants
          }
        }))
      : [{ card: group, group }]
  )
}
