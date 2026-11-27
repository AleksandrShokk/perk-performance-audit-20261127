import { describe, expect, it } from 'vitest'

import type { SupplyCard } from '@app/api'

import {
  supplyNumber,
  supplyStatus
} from '@/features/supplies/model/supplyLabels'

const plan: SupplyCard = {
  external_id: 'p:7',
  supply_id: '8',
  preorder_id: '7',
  status: 'planned',
  planned_date: null,
  actual_date: null,
  created_date: null,
  destination: '',
  quantity: 0,
  accepted_quantity: 0,
  store_id: 'store',
  store_name: 'Демо'
}

describe('готовые поставки', () => {
  it.each([
    ['draft', 'Черновик'],
    ['planned', 'Запланирована'],
    ['ready_to_ship', 'Можно отгружать'],
    ['shipped', 'Отгружена'],
    ['accepting', 'Идёт приёмка'],
    ['accepted', 'Принята']
  ] as const)('передаёт статус WB %s', (status, label) => {
    expect(supplyStatus({ ...plan, status })).toBe(label)
  })
  it('показывает отказ даже при ранее запланированном статусе', () => {
    expect(supplyStatus({ ...plan, rejected: true })).toBe('Отклонена')
  })
  it('отличает номер поставки от номера черновика', () => {
    expect(supplyNumber(plan)).toBe('Поставка №8')
    expect(supplyNumber({ ...plan, supply_id: null })).toBe('Черновик №7')
  })
})
