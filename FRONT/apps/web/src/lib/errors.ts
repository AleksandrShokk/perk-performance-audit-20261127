import { isAxiosError } from 'axios'

import { apiErrorMessage } from '@app/api'

export function statusOf(error: unknown) {
  return isAxiosError(error) ? error.response?.status : undefined
}

export function errorMessage(error: unknown) {
  return apiErrorMessage(error)
}

export function retryAfter(error: unknown) {
  if (!isAxiosError(error)) return 0
  const raw = error.response?.headers['retry-after']
  const seconds = Number(raw)
  return Number.isFinite(seconds) && seconds > 0 ? seconds : 0
}
