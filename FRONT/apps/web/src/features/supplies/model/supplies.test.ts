import { describe, expect, it } from 'vitest'

import type { ReplenishmentItem, SupplyCard } from '@app/api'

import {
  recommendationArticle,
  recommendationKey,
  recommendationPlatform,
  supplyDate,
  supplyKey,
  supplyNumber,
  supplyStatus
} from './supplies'

const recommendation: ReplenishmentItem = {
  store_id: 'wb',
  store_name: 'Store',
  nm_id: '101',
  vendor_code: 'ART',
  title: 'Product',
  photo: null,
  colors: [],
  barcodes: ['000101'],
  stock: 10,
  daily_orders: '2.5',
  days_of_stock: '4',
  quantity: 75,
  urgent: true
}
const supply: SupplyCard = {
  marketplace: 'wildberries',
  external_id: 'native',
  supply_id: '00101',
  preorder_id: null,
  status: 'ready_to_ship',
  planned_date: '2026-11-06',
  actual_date: null,
  created_date: null,
  destination: 'Warehouse',
  quantity: 0,
  accepted_quantity: null,
  store_id: 'wb',
  store_name: 'Store'
}
describe('native supply identity and display', () => {
  it('preserves native Ozon IDs, barcode zeroes and independent cabinets', () => {
    expect(recommendationArticle(recommendation, 'barcode')).toBe('000101')
    const oz = {
      ...recommendation,
      store_id: 'oz',
      nm_id: '',
      marketplace_code: '900101',
      demand_basis: 'ozon_sales' as const
    }
    expect(recommendationPlatform(oz)).toBe('ozon')
    expect(recommendationArticle(oz, 'marketplace')).toBe('Ozon 900101')
    expect(recommendationKey(recommendation)).not.toBe(
      recommendationKey({ ...recommendation, store_id: 'other' })
    )
    expect(supplyKey(supply)).not.toBe(
      supplyKey({ ...supply, store_id: 'other' })
    )
  })
  it('distinguishes native applications, supplies and drafts without exposing null IDs', () => {
    expect(supplyNumber(supply)).toBe('Поставка №00101')
    expect(
      supplyNumber({ ...supply, marketplace: 'ozon', display_number: 'ОЗ-42' })
    ).toBe('Заявка №ОЗ-42')
    expect(
      supplyNumber({ ...supply, supply_id: null, preorder_id: 'draft-1' })
    ).toBe('Черновик №draft-1')
    expect(
      supplyNumber({
        ...supply,
        marketplace: 'ozon',
        supply_id: null,
        preorder_id: null
      })
    ).toBe('Заявка №native')
  })
  it('rejection takes precedence over a generic native status', () => {
    expect(
      supplyStatus({ ...supply, status: 'accepted', rejected: true })
    ).toBe('Отклонена')
    expect(supplyStatus({ ...supply, status: 'unknown' })).toBe(
      'Статус уточняется'
    )
  })
  it('keeps API calendar dates and unknown values distinct', () => {
    expect(supplyDate('2026-11-06')).toContain('6 нояб.')
    expect(supplyDate('2026-11-06T00:00:00Z')).toBe(supplyDate('2026-11-06'))
    expect(supplyDate(null)).toBe('—')
    expect(supplyDate('broken')).toBe('—')
  })
})
