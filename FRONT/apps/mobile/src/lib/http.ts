import {
  CanceledError,
  type InternalAxiosRequestConfig,
  isAxiosError
} from 'axios'

import { configureApi, http } from '@app/api'

import { session } from '@/features/auth/session'
import { getAuthClient } from '@/features/auth/session/client'

import { apiOrigin } from './config'

/** Запросы без сессии: им не нужен токен и их 401 не означает истёкшую сессию. */
const PUBLIC_PATHS = [
  '/auth/login',
  '/auth/register',
  '/auth/refresh',
  '/auth/password/forgot',
  '/auth/password/reset'
]

type AuthorizedRequest = InternalAxiosRequestConfig & {
  sentToken?: string | null
  sentGeneration?: number
  retried?: boolean
}

function isPublic(url = '') {
  return PUBLIC_PATHS.some(path => url.includes(path))
}

let installed = false

export function setupHttp() {
  if (installed) return
  installed = true
  configureApi(apiOrigin)

  http.interceptors.request.use((config: AuthorizedRequest) => {
    if (getAuthClient() === 'web') {
      config.withCredentials = true
      if (
        session.csrfToken &&
        !['get', 'head', 'options'].includes(config.method ?? 'get')
      )
        config.headers.set('X-CSRF-Token', session.csrfToken)
    }
    if (isPublic(config.url)) return config
    config.sentToken = session.accessToken
    config.sentGeneration = session.generation
    if (session.accessToken)
      config.headers.set('Authorization', `Bearer ${session.accessToken}`)
    else config.headers.delete('Authorization')
    return config
  })

  http.interceptors.response.use(
    response => {
      const request: AuthorizedRequest = response.config
      if (
        request.sentGeneration !== undefined &&
        request.sentGeneration !== session.generation
      )
        throw new CanceledError('Сессия изменилась')
      return response
    },
    async (error: unknown) => {
      if (
        isAxiosError(error) &&
        error.config &&
        'sentGeneration' in error.config &&
        error.config.sentGeneration !== session.generation
      )
        throw new CanceledError('Сессия изменилась')

      if (
        !isAxiosError(error) ||
        error.response?.status !== 401 ||
        !error.config
      )
        throw error

      const config: AuthorizedRequest = error.config
      const sameSession = config.sentGeneration === session.generation
      if (isPublic(config.url) || !session.isActive || !sameSession) throw error
      if (config.retried) {
        await session.end()
        throw error
      }

      config.retried = true
      // Токен мог уже обновиться в соседнем запросе — тогда просто повторяем.
      if (config.sentToken === session.accessToken) await session.refresh()
      if (config.sentGeneration !== session.generation) throw error
      return http(config)
    }
  )
}
