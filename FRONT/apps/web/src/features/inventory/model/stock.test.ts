import { describe, expect, it } from 'vitest'

import type { InventoryPosition, ProductVariant } from '@app/api'

import {
  fbsVariantUnits,
  positionKey,
  positionMarketplace,
  stockCover,
  warehouseLines
} from './stock'

const variant: ProductVariant = {
  id: 'uuid-v1',
  chrt_id: '101',
  size: 'M',
  barcodes: ['000101'],
  stock: 4,
  to_client: null,
  from_client: null,
  unit_cost: null,
  warehouses: [{ name: 'Коледино', quantity: 4 }]
}
const position: InventoryPosition = {
  product: {
    id: 'product',
    store_id: 'store1',
    store_name: 'Store',
    nm_id: '1',
    vendor_code: 'A',
    title: 'Product',
    brand: '',
    subject: '',
    colors: [],
    photos: [],
    variants: [variant],
    stock: 4,
    stock_updated_at: null,
    stock_stale: false,
    missing_cost_variants: 1
  },
  fbo: { units: 4 },
  fbs: { units: 2 },
  fbs_sizes: [
    { variant_id: 'uuid-v1', quantity: 2, warehouses: { 'Склад продавца': 2 } }
  ],
  turnover_days: null,
  turnover_status: 'no_orders'
}
describe('inventory source semantics', () => {
  it('distinguishes no orders, no sales, unknown and a real zero', () => {
    expect(stockCover(null, 'no_orders')).toBe('Нет заказов за 28 дней')
    expect(stockCover(null, 'no_sales')).toBe('Нет продаж за 28 дней')
    expect(stockCover(undefined)).toBe('—')
    expect(stockCover('0')).toBe('0,0')
  })
  it('uses native FBS size IDs and preserves unknown legacy breakdowns', () => {
    expect(fbsVariantUnits(position, variant)).toBe(2)
    expect(
      fbsVariantUnits(
        {
          ...position,
          fbs_sizes: [{ chrt_id: '101', quantity: 3, warehouses: {} }]
        },
        variant
      )
    ).toBe(3)
    expect(fbsVariantUnits({ ...position, fbs_sizes: [] }, variant)).toBeNull()
    expect(
      fbsVariantUnits({ ...position, fbs: { units: null } }, variant)
    ).toBeNull()
    expect(
      fbsVariantUnits(
        { ...position, fbs: { units: 0 }, fbs_sizes: [] },
        variant
      )
    ).toBe(0)
  })
  it('keeps FBO and FBS warehouses separate and does not invent Ozon warehouses', () => {
    const before = structuredClone(position)
    expect(
      warehouseLines(position).map(row => [row.channel, row.name, row.quantity])
    ).toEqual([
      ['FBO', 'Коледино', 4],
      ['FBS', 'Склад продавца', 2]
    ])
    expect(warehouseLines(position, 'missing')).toEqual([])
    const ozon = {
      ...position,
      product: {
        ...position.product,
        variants: [{ ...variant, warehouses: [] }]
      },
      fbs_sizes: [{ variant_id: 'uuid-v1', quantity: 2, warehouses: {} }]
    }
    expect(warehouseLines(ozon)).toEqual([])
    expect(position).toEqual(before)
  })
  it('keeps cabinet identities separate and recognizes old Ozon DTOs', () => {
    expect(positionKey(position)).not.toBe(
      positionKey({
        ...position,
        product: { ...position.product, store_id: 'store2' }
      })
    )
    expect(
      positionMarketplace({ ...position, turnover_basis: 'ozon_sales_28d_fbo' })
    ).toBe('ozon')
  })
})
