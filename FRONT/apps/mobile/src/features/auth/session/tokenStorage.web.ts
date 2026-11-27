import type { SessionTokens } from './types'

export type { SessionTokens } from './types'

/** Сам токен сессии остаётся в HttpOnly cookie API и недоступен JavaScript. */
export async function readTokens(): Promise<SessionTokens | null> {
  if (typeof document === 'undefined') return null
  const value = document.cookie
    .split('; ')
    .find(cookie => cookie.startsWith('perk_csrf='))
  return value
    ? { csrfToken: decodeURIComponent(value.slice('perk_csrf='.length)) }
    : null
}

export function writeTokens(tokens: SessionTokens) {
  if (!tokens.csrfToken)
    return Promise.reject(new Error('Сервер не вернул CSRF-подтверждение'))
  // Cookies уже записаны браузером из ответа API.
  return Promise.resolve()
}

export function deleteTokens() {
  // HttpOnly cookies удаляет /auth/logout; локальную отметку убираем и без сети.
  document.cookie = 'perk_csrf=; Path=/; Max-Age=0; SameSite=Strict'
  return Promise.resolve()
}
