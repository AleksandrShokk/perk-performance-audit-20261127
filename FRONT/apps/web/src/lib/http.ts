'use client'

import {
  CanceledError,
  type InternalAxiosRequestConfig,
  isAxiosError
} from 'axios'

import { authRefresh, configureApi, http } from '@app/api'

type Request = InternalAxiosRequestConfig & {
  epoch?: number
  sentCsrf?: string | null
  retried?: boolean
}
const publicPaths = [
  '/auth/login',
  '/auth/register',
  '/auth/password/forgot',
  '/auth/password/reset',
  '/auth/refresh',
  '/auth/factor/cancel'
]

export function readCsrf() {
  if (typeof document === 'undefined') return null
  const value = document.cookie
    .split('; ')
    .find(part => part.startsWith('perk_csrf='))
  return value ? decodeURIComponent(value.slice('perk_csrf='.length)) : null
}

/** One refresh for parallel requests. The epoch rejects responses from an account that was closed. */
export function createSessionTransport() {
  let epoch = 0
  let refreshing: Promise<void> | null = null
  let installed = false
  const listeners = new Set<() => void>()
  const isPublic = (url = '') =>
    publicPaths.some(path => url.startsWith(`/api/v1${path}`))
  function end() {
    epoch += 1
    refreshing = null
    document.cookie = 'perk_csrf=; Path=/; Max-Age=0; SameSite=Strict'
    listeners.forEach(listener => listener())
  }
  function refresh() {
    if (refreshing) return refreshing
    const started = epoch
    const csrf = readCsrf()
    const perform = async () => {
      if (csrf !== readCsrf()) return
      try {
        await authRefresh({})
      } catch (error) {
        if (isAxiosError(error) && error.response?.status === 409) return
        throw error
      }
    }
    const locked =
      typeof navigator !== 'undefined' && navigator.locks
        ? navigator.locks.request('perk-session-refresh', perform)
        : perform()
    const operation = locked
      .then(() => {
        if (started !== epoch) throw new CanceledError('Сессия изменилась')
      })
      .catch(error => {
        if (
          started === epoch &&
          isAxiosError(error) &&
          error.response?.status === 401
        )
          end()
        throw error
      })
      .finally(() => {
        if (refreshing === operation) refreshing = null
      })
    refreshing = operation
    return operation
  }
  return {
    get epoch() {
      return epoch
    },
    advance() {
      epoch += 1
      refreshing = null
      return epoch
    },
    end,
    subscribe(listener: () => void) {
      listeners.add(listener)
      return () => {
        listeners.delete(listener)
      }
    },
    install() {
      if (installed) return
      installed = true
      configureApi('')
      http.defaults.withCredentials = true
      http.interceptors.request.use((config: Request) => {
        const csrf = readCsrf()
        if (
          csrf &&
          !['get', 'head', 'options'].includes(config.method ?? 'get')
        )
          config.headers.set('X-CSRF-Token', csrf)
        if (!isPublic(config.url)) {
          config.epoch = epoch
          config.sentCsrf = csrf
        }
        return config
      })
      http.interceptors.response.use(
        response => {
          const config: Request = response.config
          if (config.epoch !== undefined && config.epoch !== epoch)
            throw new CanceledError('Сессия изменилась')
          return response
        },
        async (error: unknown) => {
          if (!isAxiosError(error) || !error.config) throw error
          const config: Request = error.config
          if (config.epoch !== undefined && config.epoch !== epoch)
            throw new CanceledError('Сессия изменилась')
          if (
            error.response?.status !== 401 ||
            isPublic(config.url) ||
            !readCsrf()
          )
            throw error
          if (config.retried) {
            end()
            throw error
          }
          config.retried = true
          if (config.sentCsrf === readCsrf()) await refresh()
          if (config.epoch !== epoch)
            throw new CanceledError('Сессия изменилась')
          return http(config)
        }
      )
    }
  }
}
export const browserSession = createSessionTransport()
