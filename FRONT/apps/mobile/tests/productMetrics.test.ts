import { describe, expect, it, vi } from 'vitest'

import type { CostView, ProductItem, ProductModel } from '@app/api'

import { costSchema } from '@/features/products/model/costSchema'
import {
  modelCostLabel,
  modelIdentity,
  productCostLabel,
  productOptions,
  sortCostHistory
} from '@/features/products/model/productMetrics'

const product = (prices: (string | null)[]) =>
  ({ variants: prices.map(unit_cost => ({ unit_cost })) }) as ProductItem
describe('цены каталога', () => {
  it('известный ноль отличается от незаполненной цены', () => {
    expect(productCostLabel(product([null]), 'RUB')).toBe('Не заполнена')
    expect(productCostLabel(product(['0']), 'RUB')).toBe('0,00 ₽')
  })
  it('разные или частичные цены показываются с от, а одинаковые целиком', () => {
    expect(productCostLabel(product(['100', null]), 'RUB')).toBe('от 100,00 ₽')
    expect(productCostLabel(product(['100', '150']), 'RUB')).toBe('от 100,00 ₽')
    expect(productCostLabel(product(['100', '100']), 'RUB')).toBe('100,00 ₽')
  })
  it('принимает ноль и десятичную запятую, отклоняет отрицательные и неверные даты', () => {
    const form = { amount: '0', barcode: '', effective_from: '2026-11-02' }
    expect(costSchema.safeParse(form).success).toBe(true)
    expect(costSchema.safeParse({ ...form, amount: '120,50' }).success).toBe(
      true
    )
    expect(costSchema.safeParse({ ...form, amount: '-1' }).success).toBe(false)
    expect(costSchema.safeParse({ ...form, amount: '1.23456' }).success).toBe(
      false
    )
    expect(
      costSchema.safeParse({ ...form, effective_from: '2026-02-30' }).success
    ).toBe(false)
  })
})

it('история сортируется без toSorted и не меняет страницы кэша', () => {
  const row = (effective_from: string): CostView => ({
    nm_id: '42',
    barcode: '',
    currency: 'RUB',
    amount: '100',
    effective_from,
    created_at: '2026-11-02T10:00:00Z'
  })
  const pages = [[row('2025-01-01'), row('2026-11-02')], [row('2026-01-01')]]
  pages.forEach(Object.freeze)
  Object.freeze(pages)
  const modernSort = vi
    .spyOn(Array.prototype, 'toSorted')
    .mockImplementation(() => {
      throw new TypeError('toSorted is unavailable')
    })
  let sorted: CostView[]
  try {
    sorted = sortCostHistory(pages)
  } finally {
    modernSort.mockRestore()
  }
  expect(sorted!.map(row => row.effective_from)).toEqual([
    '2026-11-02',
    '2026-01-01',
    '2025-01-01'
  ])
  expect(pages[0]![0]!.effective_from).toBe('2025-01-01')
  expect(sortCostHistory()).toEqual([])
})

it('стоимость модели учитывает все цвета и размеры, а не только первый цвет', () => {
  const model = {
    products: [product(['100', '100']), product([null, '250'])]
  } as ProductModel
  expect(modelCostLabel(model, 'RUB')).toBe('от 100,00 ₽')
  expect(
    modelCostLabel(
      { ...model, products: [product(['0']), product(['0'])] },
      'RUB'
    )
  ).toBe('0,00 ₽')
})

it('артикулы в модели показывают наличие других цветов без потери исходных идентификаторов', () => {
  const first = {
    ...product(['100']),
    vendor_code: 'URBAN-BLACK',
    nm_id: '42',
    marketplace: 'wildberries'
  }
  const model = { products: [first, { ...first, nm_id: '43' }] } as ProductModel
  expect(modelIdentity(model, 'vendor')).toBe('URBAN-BLACK · ещё 1')
  expect(modelIdentity(model, 'wb')).toBe('WB 42 · ещё 1')
})

it('варианты с одинаковым цветом остаются различимы по артикулу', () => {
  const items = ['42', '43'].map((nm_id, index) => ({
    ...product(['100']),
    nm_id,
    colors: ['чёрный'],
    vendor_code: index ? 'URBAN-PRO' : 'URBAN'
  }))
  expect(productOptions(items).map(item => item.label)).toEqual([
    'чёрный · URBAN',
    'чёрный · URBAN-PRO'
  ])
  expect(
    productOptions(items.map(item => ({ ...item, vendor_code: 'SAME' }))).map(
      item => item.label
    )
  ).toEqual(['чёрный · SAME · 42', 'чёрный · SAME · 43'])
})

it('разные цвета показываются кратко, а неизвестные варианты имеют исходный ID', () => {
  const items = ['42', '43'].map((nm_id, index) => ({
    ...product(['100']),
    nm_id,
    colors: [index ? 'красный' : 'чёрный'],
    vendor_code: 'URBAN'
  }))
  expect(productOptions(items).map(item => item.label)).toEqual([
    'чёрный',
    'красный'
  ])
  expect(
    productOptions(
      items.map(item => ({ ...item, colors: [], vendor_code: '' }))
    ).map(item => item.label)
  ).toEqual(['42', '43'])
})
