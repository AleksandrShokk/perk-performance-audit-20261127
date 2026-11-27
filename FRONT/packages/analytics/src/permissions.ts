import type { WorkspaceResponse } from '@app/api'

import {
  ROLE_DEFAULTS as GENERATED_DEFAULTS,
  PERMISSION_OPTIONS
} from './permissions.generated'

export { PERMISSION_OPTIONS }
export type Permission = (typeof PERMISSION_OPTIONS)[number][0]
export const ROLE_LABELS: Record<string, string> = {
  owner: 'Владелец',
  admin: 'Администратор',
  manager: 'Менеджер',
  accountant: 'Бухгалтер',
  viewer: 'Наблюдатель'
}
export const ROLE_OPTIONS = [
  'manager',
  'accountant',
  'viewer',
  'admin'
] as const
export const ROLE_DEFAULTS: Record<string, string[]> = {
  ...GENERATED_DEFAULTS,
  admin: PERMISSION_OPTIONS.map(([key]) => key)
}
export const isAdminRole = (role?: string) =>
  role === 'owner' || role === 'admin'
export const permissionsFor = (workspace?: WorkspaceResponse) =>
  isAdminRole(workspace?.role)
    ? ROLE_DEFAULTS.admin!
    : (workspace?.permissions ?? [])

/** Родительское право включает связанные данные, снятие права убирает зависимые действия. */
export function togglePermission(values: string[], value: Permission) {
  const next = new Set(values)
  if (next.has(value)) {
    next.delete(value)
    if (value === 'finance.read')
      for (const item of [
        'profit.read',
        'costs.write',
        'expenses.write',
        'taxes.write'
      ])
        next.delete(item)
    if (value === 'profit.read')
      for (const item of ['costs.write', 'taxes.write']) next.delete(item)
  } else {
    next.add(value)
    if (
      ['profit.read', 'costs.write', 'expenses.write', 'taxes.write'].includes(
        value
      )
    )
      next.add('finance.read')
    if (['costs.write', 'taxes.write'].includes(value)) next.add('profit.read')
  }
  return [...next].sort()
}

export function reportPermission(topic: string): Permission {
  if (topic === 'stock') return 'inventory.read'
  if (topic === 'profit') return 'profit.read'
  if (topic === 'sales' || topic === 'finance') return 'finance.read'
  return 'analytics.read'
}

export function inviteCodeFromURL(
  url: string | null | undefined
): string | null {
  const code = url?.match(/[?#&]code=(pw_[A-Za-z0-9_-]{43})(?:&|$)/)?.[1]
  return code ?? null
}

/** Expo Go открывает путь после /--/; установленное приложение использует perk://. */
export function inviteAppURL(
  pageURL: string,
  code: string,
  development: boolean
) {
  const base = development
    ? `exp://${new URL(pageURL).host}/--/invite`
    : 'perk://invite'
  return `${base}?code=${encodeURIComponent(code)}`
}
