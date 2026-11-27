import { describe, expect, it } from 'vitest'

import type { ProductItem, ProductModel, ProductVariant } from '@app/api'

import {
  catalogRows,
  costRange,
  exactCost,
  identifier,
  productOptions
} from './catalog'
import { costSchema } from './cost-schema'

const variant = (id: string, cost: string | null): ProductVariant => ({
  id,
  chrt_id: id,
  size: 'M',
  barcodes: [`000${id}`],
  stock: null,
  to_client: null,
  from_client: null,
  warehouses: [],
  unit_cost: cost
})
const product = (id: string, cost: string | null): ProductItem => ({
  id,
  nm_id: id,
  store_id: 'store',
  store_name: 'Test',
  vendor_code: `ART-${id}`,
  marketplace_code: id,
  marketplace: 'wildberries',
  title: 'Одинаковое название',
  brand: 'Test',
  subject: '',
  colors: ['чёрный'],
  photos: [],
  variants: [variant(id, cost)],
  stock: null,
  stock_updated_at: null,
  stock_stale: false,
  missing_cost_variants: cost == null ? 1 : 0
})
const model = (id: string, products: ProductItem[]): ProductModel => ({
  id,
  products,
  store_id: 'store',
  store_name: 'Test',
  marketplace: 'wildberries',
  title: 'Одинаковое название',
  brand: 'Test',
  grouping: 'marketplace',
  stock: null,
  missing_cost_variants: null
})

describe('native catalog cards', () => {
  it('never merges identical names or articles from separate API groups', () => {
    const a = model('native-a', [
      product('101', '1200'),
      product('102', '1300')
    ])
    const b = model('native-b', [product('103', null)])
    expect(catalogRows([a, b], false).map(row => row.model.id)).toEqual([
      'native-a',
      'native-b'
    ])
    const expanded = catalogRows([a, b], true)
    expect(expanded).toHaveLength(3)
    expect(expanded[1]!.model).toBe(a)
    expect(expanded[1]!.initialProduct).toBe('102')
    expect(expanded[1]!.model.products).toHaveLength(2)
    expect(expanded[0]!.stock).toBeNull()
  })
  it('keeps IDs separate across cabinets and preserves Ozon native identity', () => {
    const wb = model('same-id', [product('101', null)])
    const oz = {
      ...model('same-id', [product('101', null)]),
      store_id: 'other-store',
      marketplace: 'ozon'
    }
    const rows = catalogRows([wb, oz], true)
    expect(rows[0]!.key).not.toBe(rows[1]!.key)
    expect(
      identifier(
        { ...product('101', null), nm_id: '', marketplace_code: '900001' },
        'marketplace',
        'ozon'
      )
    ).toBe('Ozon 900001')
  })
  it('preserves leading zeroes and disambiguates duplicate color labels', () => {
    const a = product('101', null),
      b = product('102', null)
    expect(identifier(a, 'barcode', 'wildberries')).toBe('000101')
    expect(identifier(a, 'vendor', 'wildberries')).toBe('ART-101')
    expect(
      new Set(productOptions([a, b]).map(option => option.label)).size
    ).toBe(2)
  })
})
describe('unit cost precision', () => {
  it('groups only the integer digits, retaining all four fractional digits', () => {
    expect(exactCost('1234567.1234', 'RUB')).toBe('1\u00a0234\u00a0567,1234 ₽')
    expect(exactCost('0', 'RUB')).toBe('0,00 ₽')
    expect(exactCost(null, 'RUB')).toBe('—')
    expect(exactCost('Infinity', 'RUB')).toBe('—')
  })
  it('does not turn missing prices into zero or treat a partial range as complete', () => {
    expect(costRange([product('101', null)], 'RUB').label).toBe('—')
    const range = costRange(
      [product('101', '0'), product('102', '1500'), product('103', null)],
      'RUB'
    )
    expect(range.partial).toBe(true)
    expect(range.label).toContain('0,00 ₽')
    expect(range.label).toContain('1\u00a0500,00 ₽')
  })
  it('accepts zero cost and decimal commas, rejects negative prices and impossible dates', () => {
    const input = {
      amount: '0',
      effective_from: '2026-11-06',
      barcode: '000123'
    }
    expect(costSchema.parse(input).amount).toBe('0')
    expect(costSchema.parse({ ...input, amount: '1234,5678' }).amount).toBe(
      '1234.5678'
    )
    expect(costSchema.safeParse({ ...input, amount: '-1' }).success).toBe(false)
    expect(costSchema.safeParse({ ...input, amount: '1.00001' }).success).toBe(
      false
    )
    expect(
      costSchema.safeParse({ ...input, effective_from: '2026-02-31' }).success
    ).toBe(false)
  })
})
