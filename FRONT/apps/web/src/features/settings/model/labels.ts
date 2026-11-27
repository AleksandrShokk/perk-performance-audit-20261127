export function connectionLabel(status?: string) {
  return status
    ? ({
        connected: 'Подключён',
        expired: 'Токен истёк',
        invalid_token: 'Ключ недействителен',
        disconnected: 'Отключён',
        not_connected: 'Не подключён'
      }[status] ?? 'Проверьте подключение')
    : '—'
}
export function settingsDate(value?: string | null, time = false) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? '—'
    : new Intl.DateTimeFormat('ru-RU', {
        day: 'numeric',
        month: 'short',
        year: 'numeric',
        ...(time ? { hour: '2-digit', minute: '2-digit' } : {})
      }).format(date)
}
