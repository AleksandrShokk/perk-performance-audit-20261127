import { isAxiosError } from 'axios'

import {
  type ApiErrorBody,
  apiErrorMessage,
  apiRetryAfterSeconds
} from '@app/api'

function body(error: unknown): ApiErrorBody | undefined {
  return isAxiosError<ApiErrorBody>(error) ? error.response?.data : undefined
}

function detail(error: unknown): Record<string, unknown> | undefined {
  const value = body(error)?.detail
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined
}

export function errorStatus(error: unknown) {
  return isAxiosError(error) ? error.response?.status : undefined
}

/** Ожидание, которое назначил сервер после ограничения частоты запросов. */
export function retryAfterSeconds(error: unknown): number {
  return apiRetryAfterSeconds(error)
}

/** Машиночитаемая причина ошибки API: `otp_invalid`, `step_up_required`… */
export function errorCode(error: unknown) {
  return body(error)?.code
}

/** Сервер просит подтвердить действие кодом. `strong` — нельзя подтверждать почтой. */
export function stepUpRequirement(error: unknown) {
  if (errorStatus(error) !== 403 || errorCode(error) !== 'step_up_required')
    return null
  return { strong: detail(error)?.strong === true }
}

/** Понятный текст ошибки для пользователя. */
export function errorMessage(error: unknown, fallback?: string): string {
  return apiErrorMessage(error, fallback)
}
