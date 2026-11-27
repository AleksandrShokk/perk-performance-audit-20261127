import { describe, expect, it } from 'vitest'

import {
  parseProductLabelMode,
  productLabel
} from '@/features/products/model/productLabel'

describe('обозначение товара в отчёте', () => {
  const product = {
    nm_id: '42',
    vendor_code: 'SELLER-42',
    barcodes: ['000123', '000456']
  }
  it('меняет только подпись, сохраняя ведущие нули штрихкода', () => {
    expect(productLabel(product, 'vendor')).toBe('SELLER-42')
    expect(productLabel(product, 'wb')).toBe('WB 42')
    expect(productLabel(product, 'barcode')).toBe('000123 +1')
    expect(productLabel({ ...product, barcodes: ['000123'] }, 'barcode')).toBe(
      '000123'
    )
    expect(product.barcodes).toEqual(['000123', '000456'])
  })
  it('возвращается к WB, когда нужного идентификатора нет', () => {
    expect(productLabel({ nm_id: '42' }, 'vendor')).toBe('WB 42')
    expect(productLabel({ nm_id: '42', barcodes: [] }, 'barcode')).toBe('WB 42')
    expect(productLabel({ nm_id: '42', vendor_code: '   ' }, 'vendor')).toBe(
      'WB 42'
    )
  })
  it('проверяет сохранённое предпочтение', () => {
    expect(parseProductLabelMode('vendor')).toBe('vendor')
    expect(parseProductLabelMode('barcode')).toBe('barcode')
    expect(parseProductLabelMode('invalid')).toBe('wb')
    expect(parseProductLabelMode(null)).toBe('wb')
  })
})
