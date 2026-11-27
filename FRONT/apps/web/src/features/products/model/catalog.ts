import { currencySymbol } from '@app/analytics/format'
import { Decimal } from 'decimal.js'

import type { ProductItem, ProductModel, ProductVariant } from '@app/api'

import { financeMoney } from '@/features/finance/model/finance-format'

export const identifierModes = [
  ['vendor', 'Артикул продавца'],
  ['marketplace', 'Артикул площадки'],
  ['barcode', 'Штрихкод']
] as const
export type IdentifierMode = (typeof identifierModes)[number][0]
export const productKey = (product: ProductItem) =>
  product.id ||
  product.nm_id ||
  product.external_id ||
  product.marketplace_code ||
  product.vendor_code
export const variantKey = (variant: ProductVariant) =>
  variant.id ||
  variant.chrt_id ||
  variant.external_id ||
  variant.barcodes.join(':')
export const platformName = (marketplace = 'wildberries') =>
  marketplace === 'combined'
    ? 'WB + Ozon'
    : marketplace === 'ozon'
      ? 'Ozon'
      : 'WB'
export function identifier(
  product: ProductItem,
  mode: IdentifierMode,
  marketplace = 'wildberries'
) {
  const codes = product.variants.flatMap(variant => variant.barcodes)
  if (mode === 'vendor' && product.vendor_code.trim())
    return product.vendor_code.trim()
  if (mode === 'barcode' && codes.length)
    return `${codes[0]}${codes.length > 1 ? ` +${codes.length - 1}` : ''}`
  return `${platformName(marketplace)} ${product.marketplace_code || product.nm_id || product.external_id || '—'}`
}
export type CatalogRow = {
  key: string
  model: ProductModel
  products: ProductItem[]
  initialProduct?: string
  title: string
  stock: number | null
}
/** Card membership is defined by the API. Expanding the feed never changes that membership. */
export function catalogRows(
  models: ProductModel[],
  showVariants: boolean
): CatalogRow[] {
  return models.flatMap<CatalogRow>(model =>
    showVariants
      ? model.products.map(product => ({
          key: `${model.store_id}:${model.id}:${productKey(product)}`,
          model,
          products: [product],
          initialProduct: productKey(product),
          title: product.title,
          stock: product.stock
        }))
      : [
          {
            key: `${model.store_id}:${model.id}`,
            model,
            products: model.products,
            title: model.title,
            stock: model.stock
          }
        ]
  )
}
export function productOptions(products: ProductItem[]) {
  const labels = products.map(
    product =>
      product.colors.join(', ') ||
      product.vendor_code ||
      product.marketplace_code ||
      product.nm_id ||
      productKey(product)
  )
  return products.map((product, index) => ({
    product,
    label:
      labels.filter(label => label === labels[index]).length > 1
        ? `${labels[index]} · ${product.vendor_code || product.marketplace_code || product.nm_id || productKey(product)}`
        : labels[index]!
  }))
}
export function sizeLabel(variant: ProductVariant) {
  return variant.size && variant.size !== '0'
    ? variant.size
    : `Вариант ${variant.external_id || variant.chrt_id || variantKey(variant)}`
}
export function costRange(products: ProductItem[], currency: string) {
  const variants = products.flatMap(product => product.variants)
  const known = variants.flatMap(variant => {
    if (variant.unit_cost == null) return []
    try {
      const value = new Decimal(variant.unit_cost)
      return value.isFinite() ? [value] : []
    } catch {
      return []
    }
  })
  if (!known.length) return { label: '—', partial: variants.length > 0 }
  const min = Decimal.min(...known),
    max = Decimal.max(...known)
  return {
    label: min.eq(max)
      ? financeMoney(min.toFixed(), currency)
      : `${financeMoney(min.toFixed(), currency)} – ${financeMoney(max.toFixed(), currency)}`,
    partial: known.length !== variants.length
  }
}
export function exactCost(value: string | null, currency: string) {
  if (value == null) return '—'
  try {
    const number = new Decimal(value)
    if (!number.isFinite()) return '—'
    const [whole, fraction] = number
      .toFixed(Math.max(2, Math.min(4, number.decimalPlaces())))
      .split('.')
    return `${whole!.replace(/\B(?=(\d{3})+(?!\d))/g, '\u00a0')},${fraction} ${currencySymbol(currency)}`
  } catch {
    return '—'
  }
}
