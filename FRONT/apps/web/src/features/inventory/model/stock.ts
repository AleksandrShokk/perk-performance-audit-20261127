import { formatNumber } from '@app/analytics/format'

import type {
  InventoryOverview,
  InventoryPosition,
  ProductVariant
} from '@app/api'

import { variantKey } from '@/features/products/model/catalog'

type Basis =
  InventoryOverview['turnover_basis'] | InventoryPosition['turnover_basis']
export function stockBasisTitle(basis?: Basis) {
  return basis === 'ozon_orders_28d_fbs' ? 'Запас FBS, дней' : 'Запас в днях'
}
export function stockCover(
  value: string | null | undefined,
  status?: InventoryPosition['turnover_status']
) {
  if (value != null) return formatNumber(value, 1)
  switch (status) {
    case 'no_orders':
      return 'Нет заказов за 28 дней'
    case 'no_sales':
      return 'Нет продаж за 28 дней'
    case 'loading':
      return 'Загружаем…'
    case 'no_data':
      return 'Недостаточно данных'
    default:
      return '—'
  }
}
export function positionKey(position: InventoryPosition) {
  const product = position.product
  return `${product.store_id}:${product.id || product.nm_id || product.external_id || product.marketplace_code}`
}
export function positionMarketplace(position: InventoryPosition) {
  return (
    position.product.marketplace ||
    (position.turnover_basis === 'ozon_sales_28d_fbo' ? 'ozon' : 'wildberries')
  )
}
export function fbsForVariant(
  position: InventoryPosition,
  variant: ProductVariant
) {
  return position.fbs_sizes?.find(
    row =>
      (!!row.variant_id && !!variant.id && row.variant_id === variant.id) ||
      (!!row.chrt_id && row.chrt_id === variant.chrt_id)
  )
}
export function fbsVariantUnits(
  position: InventoryPosition,
  variant: ProductVariant
) {
  if (position.fbs.units == null) return null
  const matched = fbsForVariant(position, variant)
  if (matched) return matched.quantity
  // An empty legacy size map cannot explain a positive aggregate stock.
  return position.fbs.units === 0 || !!position.fbs_sizes?.length ? 0 : null
}
export type WarehouseLine = {
  key: string
  channel: 'FBO' | 'FBS'
  name: string
  variant: ProductVariant
  quantity: number
}
/** Keep the source channel and size. No distribution of an aggregate across invented warehouses. */
export function warehouseLines(
  position: InventoryPosition,
  size = 'all'
): WarehouseLine[] {
  return position.product.variants
    .filter(variant => size === 'all' || variantKey(variant) === size)
    .flatMap(variant => [
      ...variant.warehouses.map((row, index) => ({
        key: `fbo:${variantKey(variant)}:${row.name}:${index}`,
        channel: 'FBO' as const,
        name: row.name || 'Склад маркетплейса',
        variant,
        quantity: row.quantity
      })),
      ...Object.entries(fbsForVariant(position, variant)?.warehouses ?? {}).map(
        ([name, quantity]) => ({
          key: `fbs:${variantKey(variant)}:${name}`,
          channel: 'FBS' as const,
          name: name || 'Склад продавца',
          variant,
          quantity
        })
      )
    ])
}
