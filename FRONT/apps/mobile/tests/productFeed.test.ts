import { expect, it } from 'vitest'

import type { ProductItem, ProductModel } from '@app/api'

import { productFeed } from '@/features/products/model/productFeed'

function product(
  nm_id: string,
  store_id = 'first',
  stock: number | null = 3
): ProductItem {
  return {
    nm_id,
    store_id,
    store_name: store_id,
    title: `Товар ${nm_id}`,
    vendor_code: nm_id,
    brand: 'PERK',
    subject: '',
    colors: ['чёрный'],
    photos: [nm_id + '.jpg'],
    stock,
    stock_updated_at: null,
    stock_stale: false,
    missing_cost_variants: stock === null ? null : 0,
    variants: [
      {
        chrt_id: nm_id,
        size: 'M',
        barcodes: [nm_id],
        stock,
        unit_cost: '0',
        to_client: null,
        from_client: null,
        warehouses: []
      }
    ]
  }
}
function card(id: string, products: ProductItem[]): ProductModel {
  return {
    id,
    store_id: products[0]!.store_id,
    store_name: '',
    marketplace: 'wildberries',
    title: 'Общая карточка',
    brand: 'PERK',
    grouping: 'marketplace',
    products,
    stock: 10,
    missing_cost_variants: 0
  }
}

it('обычный список сохраняет карточки площадки целиком', () => {
  const group = card('first:100', [product('42'), product('43')])
  const rows = productFeed([group], false)
  expect(rows).toEqual([{ card: group, group }])
  expect(rows[0]!.card).toBe(group)
  expect(rows[0]!.selectedProduct).toBeUndefined()
})

it('разворачивает артикулы с их фото и показателями, сохраняя общую карточку для открытия', () => {
  const first = product('42')
  const second = product('43', 'first', null)
  const group = card('first:100', [first, second])
  Object.freeze(group.products)
  Object.freeze(group)
  const rows = productFeed([group], true)
  expect(rows).toHaveLength(2)
  expect(rows.map(row => row.selectedProduct?.nm_id)).toEqual(['42', '43'])
  expect(
    rows.every(row => row.group === group && row.group.products.length === 2)
  ).toBe(true)
  expect(rows[1]!.card.products).toEqual([second])
  expect(rows[1]!.card.title).toBe(second.title)
  expect(rows[1]!.card.products[0]!.photos).toEqual(['43.jpg'])
  expect(rows[1]!.card.stock).toBeNull()
  expect(rows[1]!.card.missing_cost_variants).toBeNull()
  expect(rows[0]!.card.products[0]!.variants[0]!.unit_cost).toBe('0')
})

it('одинаковые артикулы из разных магазинов имеют разные ключи и не смешиваются', () => {
  const groups = [
    card('first:100', [product('42')]),
    card('second:100', [product('42', 'second')])
  ]
  const rows = productFeed(groups, true)
  expect(new Set(rows.map(row => row.card.id)).size).toBe(2)
  expect(rows.map(row => row.group.store_id)).toEqual(['first', 'second'])
  expect(productFeed([], true)).toEqual([])
})
