import { type TokenResponse, authRefresh } from '@app/api'

import { errorStatus } from '@/lib/errors'

import { getAuthClient } from './client'
import {
  type SessionTokens,
  deleteTokens,
  readTokens,
  writeTokens
} from './tokenStorage'

/**
 * Токены текущей сессии. Компоненты с ними не работают: запросы получают
 * авторизацию через перехватчики (lib/http.ts), состояние входа — через useAuth.
 */
let tokens: SessionTokens | null = null
/** Растёт при каждом входе и выходе: поздний ответ старой сессии игнорируется. */
let generation = 0
let refreshing: Promise<void> | null = null
const endListeners = new Set<() => void | Promise<void>>()
let storageQueue = Promise.resolve()

function updateStorage(action: () => Promise<void>) {
  const result = storageQueue.then(action)
  storageQueue = result.catch(() => {})
  return result
}

function fromResponse(response: TokenResponse): SessionTokens {
  if (getAuthClient() === 'web') {
    if (!response.csrf_token)
      throw new Error('Сервер не вернул CSRF-подтверждение')
    return { csrfToken: response.csrf_token }
  }
  if (!response.access_token || !response.refresh_token)
    throw new Error('Сервер не вернул токены сессии')
  return {
    accessToken: response.access_token,
    refreshToken: response.refresh_token
  }
}

export const session = {
  get accessToken() {
    return tokens?.accessToken ?? null
  },

  get isActive() {
    return tokens !== null
  },

  get csrfToken() {
    return tokens?.csrfToken ?? null
  },

  get generation() {
    return generation
  },

  /** Читает сохранённую сессию при запуске. */
  async restore() {
    const current = generation
    const saved = await readTokens()
    if (current === generation) tokens = saved
    return tokens !== null
  },

  async start(response: TokenResponse) {
    const next = fromResponse(response)
    generation += 1
    refreshing = null
    const started = generation
    // После MFA старая сессия уже отозвана: новые запросы сразу получают новую.
    tokens = next
    try {
      await updateStorage(() => writeTokens(next))
    } catch (error) {
      if (started === generation) await session.end()
      throw error
    }
    return started
  },

  async end() {
    generation += 1
    tokens = null
    refreshing = null
    await Promise.all([
      updateStorage(deleteTokens),
      ...Array.from(endListeners, listener => Promise.resolve().then(listener))
    ])
  },

  /** Одно обновление на все параллельные запросы: повторный refresh отзывает сессию. */
  refresh(): Promise<void> {
    if (refreshing) return refreshing
    const current = tokens
    if (!current) return Promise.reject(new Error('Сессия отсутствует'))
    const started = generation

    let rotated = false
    const operation = authRefresh(
      getAuthClient() === 'web' ? {} : { refresh_token: current.refreshToken }
    )
      .then(async response => {
        if (started !== generation) return
        const next = fromResponse(response)
        rotated = true
        await updateStorage(() => writeTokens(next))
        if (started === generation) tokens = next
      })
      .catch(async error => {
        if (started === generation && (rotated || errorStatus(error) === 401))
          await session.end()
        throw error
      })
      .finally(() => {
        if (refreshing === operation) refreshing = null
      })

    refreshing = operation
    return operation
  },

  /** Сессия закончилась: выход, отзыв или неудачное обновление. */
  onEnd(listener: () => void | Promise<void>) {
    endListeners.add(listener)
    return () => {
      endListeners.delete(listener)
    }
  }
}
