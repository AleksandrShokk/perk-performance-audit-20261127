import { describe, expect, it } from 'vitest'

import { supplyPlanUpdateSchema } from '@app/schemas'

import type { PlanView } from '@app/api'

import { matchingPlanItems, planValues } from './plans'

const plan = {
  revision: 3,
  title: 'План',
  destination: 'Коледино',
  status: 'draft',
  items: [
    {
      product_key: 'a',
      quantity: 10,
      box_multiple: 5,
      title: 'Шлем',
      vendor_code: 'WB-1',
      marketplace_code: '123',
      nm_id: '123',
      barcodes: ['000123']
    },
    {
      product_key: 'b',
      quantity: 6,
      box_multiple: 6,
      title: 'Ботинки',
      vendor_code: 'WB-2',
      marketplace_code: '456',
      nm_id: '456',
      barcodes: ['000456']
    }
  ]
} as PlanView

describe('saved supply plans', () => {
  it('matches identifiers and keeps original form indexes after filtering', () => {
    expect(matchingPlanItems(plan, '  БОТИНКИ ')[0]?.index).toBe(1)
    expect(matchingPlanItems(plan, '000123')[0]?.index).toBe(0)
    expect(matchingPlanItems(plan, '456')).toHaveLength(1)
    expect(matchingPlanItems(plan, 'missing')).toEqual([])
  })
  it('sends quantities only and does not mutate the snapshot', () => {
    const values = planValues(plan)
    values.items[0]!.quantity = 0
    expect(plan.items[0]!.quantity).toBe(10)
    expect(values.items[0]).toEqual({ product_key: 'a', quantity: 0 })
    expect(values.revision).toBe(3)
  })
  it('checks whole box multiples and prevents an empty ready plan', () => {
    const schema = supplyPlanUpdateSchema(plan.items)
    expect(schema.safeParse(planValues(plan)).success).toBe(true)
    const values = planValues(plan)
    values.items[0]!.quantity = 11
    expect(schema.safeParse(values).success).toBe(false)
    values.items[0]!.quantity = 1.5
    expect(schema.safeParse(values).success).toBe(false)
    values.items.forEach(item => {
      item.quantity = 0
    })
    expect(schema.safeParse(values).success).toBe(true)
    expect(schema.safeParse({ ...values, status: 'ready' }).success).toBe(false)
  })
})

describe('native size allocation', () => {
  const withSizes = {
    ...plan,
    items: [
      {
        ...plan.items[0]!,
        variants: [
          {
            variant_id: 'size1',
            external_id: '10',
            size: 'S',
            barcodes: ['001', '002'],
            barcode: '002',
            quantity: 4
          },
          {
            variant_id: 'size2',
            external_id: '11',
            size: 'L',
            barcodes: ['003'],
            barcode: '003',
            quantity: 6
          }
        ]
      }
    ]
  } as PlanView
  it('sends IDs, quantities and one selected barcode without trusting metadata', () => {
    const values = planValues(withSizes)
    expect(values.items[0]!.variants?.[0]).toEqual({
      variant_id: 'size1',
      quantity: 4,
      barcode: '002'
    })
    values.items[0]!.variants![0]!.quantity = 0
    expect(withSizes.items[0]!.variants![0]!.quantity).toBe(4)
    expect(matchingPlanItems(withSizes, 'S')).toHaveLength(1)
  })
  it('allows incomplete drafts, but rejects excess quantity and unrelated barcodes', () => {
    const schema = supplyPlanUpdateSchema(withSizes.items),
      values = planValues(withSizes)
    values.items[0]!.variants![0]!.quantity = 1
    expect(schema.safeParse(values).success).toBe(true)
    values.items[0]!.variants![0]!.quantity = 100
    expect(schema.safeParse(values).success).toBe(false)
    values.items[0]!.variants![0]!.quantity = 4
    values.items[0]!.variants![0]!.barcode = '999'
    expect(schema.safeParse(values).success).toBe(false)
  })
})
