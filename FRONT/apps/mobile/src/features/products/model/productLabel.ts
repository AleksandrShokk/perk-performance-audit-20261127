export const PRODUCT_LABEL_OPTIONS = [
  { value: 'vendor', label: 'Артикул продавца' },
  { value: 'wb', label: 'Артикул площадки' },
  { value: 'barcode', label: 'Штрихкод' }
] as const

export type ProductLabelMode = (typeof PRODUCT_LABEL_OPTIONS)[number]['value']
export type ProductIdentity = {
  nm_id?: string
  marketplace_code?: string
  vendor_code?: string | null
  marketplace?: string
  barcodes?: string[]
}

export function parseProductLabelMode(value: string | null): ProductLabelMode {
  return value === 'vendor' || value === 'barcode' ? value : 'wb'
}

export function productLabel(product: ProductIdentity, mode: ProductLabelMode) {
  if (mode === 'vendor' && product.vendor_code?.trim())
    return product.vendor_code.trim()
  if (mode === 'barcode' && product.barcodes?.length) {
    const [first, ...others] = product.barcodes
    return others.length ? `${first} +${others.length}` : first!
  }
  return `${product.marketplace === 'ozon' ? 'Ozon' : 'WB'} ${product.marketplace_code || product.nm_id || '—'}`
}
