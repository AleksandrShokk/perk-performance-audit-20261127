import { webApiOrigin } from './webApiOrigin'

const configured =
  process.env.EXPO_PUBLIC_WEB_API_URL ?? process.env.EXPO_PUBLIC_API_URL
if (!configured)
  throw new Error('Не задан адрес API для браузера — см. .env.example')

export const apiOrigin = webApiOrigin(
  configured,
  typeof window === 'undefined' ? undefined : window.location.href,
  __DEV__
)
