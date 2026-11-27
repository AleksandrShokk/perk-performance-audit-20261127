import { describe, expect, it } from 'vitest'

import { turnoverLabel } from '@/features/inventory/model/stockCover'

describe('подпись запаса в днях', () => {
  it('показывает известный ноль как число дней', () => {
    expect(turnoverLabel('0.00', 'ready')).toBe('0,0 дн.')
    expect(turnoverLabel('20.25', 'ready')).toBe('20,3 дн.')
  })
  it('отличает отсутствие заказов от неизвестных данных и загрузки', () => {
    expect(turnoverLabel(null, 'no_orders')).toBe('Нет заказов за 28 дней')
    expect(turnoverLabel(null, 'no_data')).toBe('Недостаточно данных')
    expect(turnoverLabel(null, 'loading')).toBe('Загружаем…')
  })
  it('сохраняет результат при фоновом обновлении', () => {
    expect(turnoverLabel('12', 'loading')).toBe('12,0 дн.')
  })
  it('не объявляет отсутствие заказов для старого ответа без статуса', () => {
    expect(turnoverLabel(null)).toBe('—')
    expect(turnoverLabel(undefined)).toBe('—')
  })
})
