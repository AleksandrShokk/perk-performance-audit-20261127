const CONNECTION_LABELS: Record<string, string> = {
  connected: 'Подключён',
  expired: 'Токен истёк',
  invalid_token: 'Токен недействителен',
  disconnected: 'Отключён',
  not_connected: 'Не подключён'
}

export function connectionLabel(status: string | undefined) {
  return status ? (CONNECTION_LABELS[status] ?? 'Проверьте подключение') : '—'
}

export function tokenExpiryLabel(value: string | null | undefined) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleDateString('ru-RU')
}
