import { isAxiosError } from 'axios'

import type { ApiErrorBody } from './client'

const FALLBACK = 'Что-то пошло не так. Попробуйте ещё раз.'
const RUSSIAN = /[а-яё]/i

// Older API versions may still send these messages during an update.
const LEGACY_MESSAGES: Record<string, string> = {
  'Production requires a WB service token issued for PERK':
    'Для подключения WB нужен сервисный токен, выданный для PERK.',
  'Invalid email or password': 'Неверный email или пароль.',
  'Authentication required': 'Войдите в аккаунт.',
  'Invalid session': 'Сессия завершена. Войдите снова.',
  'Session revoked; sign in again': 'Сессия завершена. Войдите снова.',
  'Store not found': 'Магазин не найден.',
  'Workspace not found': 'Кабинет не найден.',
  'Store already connected in this workspace':
    'Этот магазин уже подключён к кабинету.',
  'Token belongs to another seller': 'Токен относится к другому продавцу WB.',
  'Invalid or expired WB token':
    'Токен WB недействителен или срок его действия истёк.',
  'PERK accepts read-only WB tokens only': 'Нужен токен WB только для чтения.',
  'WB rejected the token':
    'Wildberries отклонил токен. Проверьте его или создайте новый.',
  'WB verification unavailable':
    'Не удалось проверить токен Wildberries. Попробуйте позже.',
  'WB token has no supported analytics permissions':
    'У токена WB нет нужных прав для аналитики.',
  'WB token has unnecessary permissions; remove users and communications access':
    'Уберите из токена WB доступ к пользователям и коммуникациям.'
}

const STATUS_MESSAGES: Record<number, string> = {
  400: 'Проверьте введённые данные.',
  401: 'Войдите в аккаунт.',
  403: 'Недостаточно прав для этого действия.',
  404: 'Запрошенные данные не найдены.',
  405: 'Это действие недоступно.',
  409: 'Данные изменились. Обновите страницу и повторите действие.',
  410: 'Данные больше недоступны.',
  413: 'Файл слишком большой. Выберите файл меньшего размера.',
  415: 'Этот формат файла не поддерживается.',
  422: 'Проверьте введённые данные'
}

export function apiErrorBody(error: unknown): ApiErrorBody | undefined {
  const value = isAxiosError(error) ? error.response?.data : undefined
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as ApiErrorBody)
    : undefined
}

export function localizedErrorText(message: unknown): string | undefined {
  if (typeof message !== 'string') return undefined
  const value = message.trim()
  return LEGACY_MESSAGES[value] ?? (RUSSIAN.test(value) ? value : undefined)
}

export function apiRetryAfterSeconds(error: unknown): number {
  if (!isAxiosError(error) || error.response?.status !== 429) return 0
  const header = error.response.headers?.['retry-after']
  if (typeof header !== 'string' && typeof header !== 'number') return 60
  const seconds = Number(header)
  if (Number.isFinite(seconds) && seconds >= 0) return Math.ceil(seconds)
  const deadline = Date.parse(String(header))
  return Number.isFinite(deadline)
    ? Math.max(0, Math.ceil((deadline - Date.now()) / 1000))
    : 60
}

/** Only Russian user-facing messages; raw technical exceptions stay out of the UI. */
export function apiErrorMessage(error: unknown, fallback = FALLBACK): string {
  const safeFallback = localizedErrorText(fallback) ?? FALLBACK
  if (!isAxiosError(error))
    return error instanceof Error
      ? (localizedErrorText(error.message) ?? safeFallback)
      : safeFallback
  if (error.code === 'ECONNABORTED' || error.code === 'ETIMEDOUT')
    return 'Сервер не ответил вовремя. Попробуйте ещё раз.'
  if (!error.response)
    return 'Нет связи с сервером. Проверьте интернет и попробуйте снова.'

  const status = error.response.status
  if (status === 429) {
    const seconds = apiRetryAfterSeconds(error)
    const wait =
      seconds >= 60 ? `${Math.ceil(seconds / 60)} мин.` : `${seconds} с.`
    return `Слишком много попыток. Повторите через ${wait}`
  }
  const body = apiErrorBody(error)
  const detail = body?.detail
  const nested =
    detail && typeof detail === 'object' && !Array.isArray(detail)
      ? (detail as Record<string, unknown>).message
      : undefined
  for (const candidate of [body?.message, nested, detail]) {
    const translated = localizedErrorText(candidate)
    if (translated) return translated
  }
  if (status >= 500) return 'Сервер временно недоступен. Попробуйте позже.'
  return STATUS_MESSAGES[status] ?? safeFallback
}
