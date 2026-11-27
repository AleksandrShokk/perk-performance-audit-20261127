import type { ReplenishmentItem, SupplyCard } from '@app/api'

import {
  type IdentifierMode,
  platformName
} from '@/features/products/model/catalog'

export function recommendationKey(item: ReplenishmentItem) {
  return `${item.store_id}:${item.id || item.nm_id || item.marketplace_code || item.vendor_code}`
}
export function supplyKey(item: SupplyCard) {
  return `${item.store_id}:${item.external_id}`
}
export function recommendationPlatform(item: ReplenishmentItem) {
  return (
    item.marketplace ||
    (item.demand_basis === 'ozon_sales' ? 'ozon' : 'wildberries')
  )
}
export function recommendationArticle(
  item: ReplenishmentItem,
  mode: IdentifierMode
) {
  if (mode === 'barcode') return item.barcodes.join(' · ') || '—'
  const code = item.marketplace_code || item.nm_id
  if (mode === 'marketplace')
    return code ? `${platformName(recommendationPlatform(item))} ${code}` : '—'
  return item.vendor_code || code || '—'
}
export function supplyNumber(item: SupplyCard) {
  const code =
    item.display_number ||
    item.supply_id ||
    item.preorder_id ||
    item.external_id
  return `${item.marketplace === 'ozon' ? 'Заявка' : item.supply_id ? 'Поставка' : 'Черновик'} №${code}`
}
export function supplyStatus(item: SupplyCard) {
  if (item.rejected) return 'Отклонена'
  return (
    {
      draft: 'Черновик',
      planned: 'Запланирована',
      ready_to_ship: 'Готова к отгрузке',
      shipped: 'Отгружена',
      accepting: 'Идёт приёмка',
      accepted: 'Принята',
      cancelled: 'Отменена',
      unknown: 'Статус уточняется'
    }[item.status] ?? 'Статус уточняется'
  )
}
export function supplyDate(value: string | null | undefined) {
  if (!value) return '—'
  // API dates have no timezone; keep the calendar day in every browser timezone.
  const day = value.slice(0, 10)
  const date = new Date(`${day}T12:00:00Z`)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat('ru-RU', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC'
  }).format(date)
}
