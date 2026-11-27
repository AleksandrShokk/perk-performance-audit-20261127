import { Decimal } from 'decimal.js'

import type { CostView, ProductItem, ProductModel } from '@app/api'

import { formatFinanceMoney } from '@/features/finance/model/financeFormat'

import { type ProductLabelMode, productLabel } from './productLabel'

export function productCostLabel(product: ProductItem, currency: string) {
  const prices = product.variants.flatMap(variant =>
    variant.unit_cost == null ? [] : [new Decimal(variant.unit_cost)]
  )
  if (!prices.length) return 'Не заполнена'
  const min = Decimal.min(...prices),
    max = Decimal.max(...prices)
  if (!min.eq(max) || prices.length !== product.variants.length)
    return `от ${formatFinanceMoney(min.toString(), currency)}`
  return formatFinanceMoney(min.toString(), currency)
}
export function variantLabel(size: string, chrtId: string) {
  return size && size !== '0' ? size : chrtId ? `Вариант ${chrtId}` : 'Вариант'
}

/** flat создаёт новый массив: sort не меняет страницы в кэше запросов. */
export function sortCostHistory(pages: CostView[][] = []) {
  return pages
    .flat()
    .sort((a, b) => b.effective_from.localeCompare(a.effective_from))
}

export function modelCostLabel(model: ProductModel, currency: string) {
  return productCostLabel(
    {
      ...model.products[0]!,
      variants: model.products.flatMap(item => item.variants)
    },
    currency
  )
}
export function modelIdentity(model: ProductModel, mode: ProductLabelMode) {
  const [first, ...others] = model.products
  if (!first) return ''
  const label = productLabel(
    { ...first, barcodes: first.variants.flatMap(item => item.barcodes) },
    mode
  )
  return others.length ? `${label} · ещё ${others.length}` : label
}

/** Одинаковые цвета могут принадлежать разным вариантам одной карточки площадки. */
export function productOptions(products: ProductItem[]) {
  const colors = products.map(item => item.colors.join(', '))
  const onlyColors =
    colors.every(Boolean) && new Set(colors).size === products.length
  const options = products.map((product, index) => ({
    product,
    label: onlyColors
      ? colors[index]!
      : [
          colors[index],
          product.vendor_code || product.marketplace_code || product.nm_id
        ]
          .filter(Boolean)
          .join(' · ')
  }))
  return options.map(option => ({
    ...option,
    label:
      options.filter(item => item.label === option.label).length > 1
        ? `${option.label} · ${option.product.marketplace_code || option.product.nm_id}`
        : option.label
  }))
}
