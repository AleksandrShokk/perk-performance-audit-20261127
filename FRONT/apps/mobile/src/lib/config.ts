const configured = process.env.EXPO_PUBLIC_API_URL

if (!configured)
  throw new Error('Не задан EXPO_PUBLIC_API_URL — адрес API, см. .env.example')

/** Сгенерированные пути уже начинаются с /api/v1, поэтому нужен только адрес сервера. */
export const apiOrigin = configured
  .trim()
  .replace(/\/+$/, '')
  .replace(/\/api\/v1$/, '')

if (!__DEV__ && new URL(apiOrigin).protocol !== 'https:')
  throw new Error('Для рабочей сборки PERK требуется HTTPS-адрес API')
