import type { SupplyCard } from '@app/api'

export function supplyStatus(plan: SupplyCard) {
  if (plan.rejected) return 'Отклонена'
  return (
    {
      draft: 'Черновик',
      planned: 'Запланирована',
      ready_to_ship: 'Можно отгружать',
      shipped: 'Отгружена',
      accepting: 'Идёт приёмка',
      accepted: 'Принята',
      cancelled: 'Отменена',
      unknown: 'Статус уточняется'
    }[plan.status] ?? 'Статус уточняется'
  )
}

export function supplyNumber(plan: SupplyCard) {
  if (plan.marketplace === 'ozon')
    return `Заявка №${plan.display_number || plan.preorder_id}`
  return plan.supply_id
    ? `Поставка №${plan.supply_id}`
    : `Черновик №${plan.preorder_id}`
}
