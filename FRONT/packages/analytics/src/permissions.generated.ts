// Generated from OpenAPI. Do not edit.
export const PERMISSION_OPTIONS = [
  ['analytics.read', 'Аналитика'],
  ['inventory.read', 'Товары и остатки'],
  ['finance.read', 'Финансы'],
  ['profit.read', 'Себестоимость и прибыль'],
  ['costs.write', 'Изменение себестоимости'],
  ['expenses.write', 'Изменение расходов'],
  ['taxes.write', 'Налоговые настройки'],
  ['reports.export', 'Экспорт отчётов']
] as const
export const ROLE_DEFAULTS: Record<string, string[]> = {
  manager: ['analytics.read', 'inventory.read'],
  accountant: [
    'analytics.read',
    'finance.read',
    'profit.read',
    'costs.write',
    'expenses.write',
    'taxes.write',
    'reports.export'
  ],
  viewer: ['analytics.read', 'inventory.read', 'finance.read', 'profit.read']
}
