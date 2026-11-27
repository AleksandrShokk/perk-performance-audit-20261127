import { describe, expect, it } from 'vitest'

import {
  inviteAppURL,
  inviteCodeFromURL,
  isAdminRole,
  permissionsFor,
  reportPermission,
  togglePermission
} from '@/features/team/model/permissions'

describe('права сотрудников', () => {
  it('администратору доступны все права, неподтверждённый набор прав закрыт по умолчанию', () => {
    expect(
      permissionsFor({ id: 'ws', name: 'ws', role: 'admin', permissions: [] })
    ).toHaveLength(8)
    expect(permissionsFor({ id: 'ws', name: 'ws', role: 'viewer' })).toEqual([])
    expect(permissionsFor()).toEqual([])
    expect(isAdminRole('manager')).toBe(false)
  })
  it('изменение себестоимости требует финансов и просмотра прибыли', () => {
    const added = togglePermission([], 'costs.write')
    expect(added).toEqual(['costs.write', 'finance.read', 'profit.read'])
    expect(togglePermission(added, 'profit.read')).toEqual(['finance.read'])
    expect(togglePermission(added, 'finance.read')).toEqual([])
  })
  it('расходы не открывают автоматически себестоимость и прибыль', () => {
    expect(togglePermission([], 'expenses.write')).toEqual([
      'expenses.write',
      'finance.read'
    ])
  })
  it('прямые переходы на отчёты требуют того же права, что кнопки на главной', () => {
    expect(reportPermission('profit')).toBe('profit.read')
    expect(reportPermission('sales')).toBe('finance.read')
    expect(reportPermission('funnel')).toBe('analytics.read')
    expect(reportPermission('stock')).toBe('inventory.read')
  })
})

describe('ссылка приглашения', () => {
  const code = `pw_${'t'.repeat(43)}`
  it('понимает закрытый фрагмент веб-ссылки и ссылку приложения', () => {
    expect(inviteCodeFromURL(`http://localhost:8081/invite#code=${code}`)).toBe(
      code
    )
    expect(inviteCodeFromURL(`perk://invite?code=${code}`)).toBe(code)
  })
  it('отклоняет усечённый токен и произвольные параметры', () => {
    expect(inviteCodeFromURL('perk://invite?code=pw_short')).toBeNull()
    expect(inviteCodeFromURL(`perk://invite?other=${code}`)).toBeNull()
    expect(inviteCodeFromURL(null)).toBeNull()
  })
})

it('ссылка на телефоне открывает приглашение в Expo Go либо установленном приложении', () => {
  const code = `pw_${'t'.repeat(43)}`
  expect(inviteAppURL('http://192.168.1.10:8081/invite', code, true)).toBe(
    `exp://192.168.1.10:8081/--/invite?code=${code}`
  )
  expect(inviteAppURL('https://perk.example/invite', code, false)).toBe(
    `perk://invite?code=${code}`
  )
})
