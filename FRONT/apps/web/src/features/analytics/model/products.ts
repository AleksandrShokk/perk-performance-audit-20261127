import { changePercent } from '@app/analytics/sales'
import { Decimal } from 'decimal.js'

import type { FunnelProduct, FunnelReport, StoreResponse } from '@app/api'

import type { Metric } from '@/features/overview/chart-data'
import type { IdentifierMode } from '@/features/products/model/catalog'
import { platformName } from '@/features/products/model/catalog'

export type AnalyticsRow = {
  key: string
  storeId: string
  storeName: string
  marketplace: string
  current: FunnelProduct
  previous?: FunnelProduct
  currency: string | null
  previousCurrency?: string | null
  complete: boolean
  previousComplete: boolean
}
export type AnalyticsSort = Metric | 'opens' | 'carts' | 'buyout_percent'
export function nativeCode(product: FunnelProduct) {
  return product.marketplace_code || product.nm_id || product.id || ''
}
export function analyticsRows(
  stores: Pick<StoreResponse, 'id' | 'name' | 'marketplace'>[],
  reports: (FunnelReport | undefined)[],
  previous: (FunnelReport | undefined)[]
): AnalyticsRow[] {
  return stores.flatMap((store, index) => {
    const report = reports[index],
      before = previous[index]
    const past = new Map(
      before?.products.map(product => [nativeCode(product), product])
    )
    return (report?.products ?? []).map(current => ({
      key: `${store.id}:${nativeCode(current)}`,
      storeId: store.id,
      storeName: store.name,
      marketplace: store.marketplace,
      current,
      previous: past.get(nativeCode(current)),
      currency: report!.currency,
      previousCurrency: before?.currency,
      complete:
        report?.status === 'ready' && report.known_days === report.period_days,
      previousComplete:
        before?.status === 'ready' && before.known_days === before.period_days
    }))
  })
}
export function analyticsArticle(row: AnalyticsRow, mode: IdentifierMode) {
  if (mode === 'barcode') return row.current.barcodes?.join(' · ') || '—'
  if (mode === 'vendor' && row.current.vendor_code)
    return row.current.vendor_code
  return `${platformName(row.marketplace)} ${nativeCode(row.current)}`
}
export function analyticsTitle(row: AnalyticsRow) {
  return (
    row.current.title ||
    row.current.vendor_code ||
    `${platformName(row.marketplace)} · ${nativeCode(row.current)}`
  )
}
export function productChange(
  row: AnalyticsRow,
  metric: Metric,
  unit: 'units' | 'amount'
) {
  if (!row.complete || !row.previousComplete || !row.previous) return null
  const field = unit === 'amount' ? (`${metric}_amount` as const) : metric
  if (
    unit === 'amount' &&
    (!row.currency ||
      row.currency !== row.previousCurrency ||
      row.current.partial_amounts?.includes(field) ||
      row.previous.partial_amounts?.includes(field))
  )
    return null
  const current = row.current[field]
  const previous = row.previous[field]
  return changePercent(
    current == null ? null : String(current),
    previous == null ? null : String(previous)
  )
}
export function selectAnalyticsRows(
  rows: AnalyticsRow[],
  search: string,
  storeId: string,
  sort: AnalyticsSort,
  descending: boolean,
  unit: 'units' | 'amount'
) {
  const query = search.trim().toLocaleLowerCase('ru-RU')
  const selected = rows.filter(
    row =>
      (!storeId || row.storeId === storeId) &&
      (!query ||
        [
          row.current.title,
          row.current.vendor_code,
          nativeCode(row.current),
          ...(row.current.barcodes ?? [])
        ].some(value => value?.toLocaleLowerCase('ru-RU').includes(query)))
  )
  const field = (
    unit === 'amount' && ['orders', 'buyouts', 'cancellations'].includes(sort)
      ? `${sort}_amount`
      : sort
  ) as keyof FunnelProduct
  return selected.sort((a, b) => {
    const left = a.current[field],
      right = b.current[field]
    if (left == null || right == null)
      return left == null
        ? right == null
          ? a.key.localeCompare(b.key)
          : 1
        : -1
    return (
      new Decimal(String(left)).comparedTo(String(right)) *
        (descending ? -1 : 1) || a.key.localeCompare(b.key)
    )
  })
}
