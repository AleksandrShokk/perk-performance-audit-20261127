import type { InventoryPosition } from '@app/api'

import { formatNumber } from '@/lib/format'

export function turnoverLabel(
  value: string | null | undefined,
  status?: InventoryPosition['turnover_status']
) {
  if (value != null) return `${formatNumber(value, 1)} дн.`
  switch (status) {
    case 'no_sales':
      return 'Нет продаж за 28 дней'
    case 'no_orders':
      return 'Нет заказов за 28 дней'
    case 'loading':
      return 'Загружаем…'
    case 'no_data':
      return 'Недостаточно данных'
    default:
      return '—'
  }
}

export function turnoverTitle(
  basis?: InventoryPosition['turnover_basis'] | 'mixed'
) {
  return basis === 'ozon_sales_28d_fbo' ? 'Запас FBO, дней' : 'Запас в днях'
}
