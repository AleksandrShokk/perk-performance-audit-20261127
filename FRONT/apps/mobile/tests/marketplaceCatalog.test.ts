import { expect, it } from 'vitest'

import { productId, variantId } from '@/features/products/model/productIdentity'
import { productLabel } from '@/features/products/model/productLabel'
import { reportingConnections } from '@/features/workspace/model/reportingConnections'
import { selectionSupports } from '@/features/workspace/model/storeFeatures'

const wb = {
  marketplace: 'wildberries',
  features: ['catalog', 'inventory', 'finance', 'analytics', 'supplies']
}
const ozon = {
  marketplace: 'ozon',
  reports_available: false,
  features: ['catalog', 'inventory', 'analytics']
}

it('Ozon is visible for supported sections even before finance integration', () => {
  expect(reportingConnections([wb, ozon])).toEqual([wb, ozon])
  expect(selectionSupports([ozon], 'inventory')).toBe(true)
  expect(selectionSupports([ozon], 'catalog')).toBe(true)
  expect(selectionSupports([ozon], 'finance')).toBe(false)
})

it('mixed selection never presents a WB-only report as the combined result', () => {
  expect(selectionSupports([wb, ozon], 'inventory')).toBe(true)
  expect(selectionSupports([wb, ozon], 'analytics')).toBe(true)
  expect(selectionSupports([wb, ozon], 'finance')).toBe(false)
  expect(selectionSupports([wb], 'finance')).toBe(true)
  expect(selectionSupports([], 'inventory')).toBe(false)
})

it('uses the platform SKU for Ozon display and the internal ID for selection', () => {
  expect(
    productLabel(
      { marketplace: 'ozon', marketplace_code: '500', nm_id: '' },
      'wb'
    )
  ).toBe('Ozon 500')
  expect(productId({ id: 'ozon-listing-uuid', nm_id: '' })).toBe(
    'ozon-listing-uuid'
  )
  expect(variantId({ id: 'ozon-variant-uuid', chrt_id: '' })).toBe(
    'ozon-variant-uuid'
  )
  expect(productId({ nm_id: '500' })).toBe('500')
  expect(variantId({ chrt_id: '10' })).toBe('10')
})
