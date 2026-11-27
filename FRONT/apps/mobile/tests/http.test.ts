import {
  AxiosError,
  AxiosHeaders,
  type InternalAxiosRequestConfig
} from 'axios'
import { beforeEach, expect, it, vi } from 'vitest'

import { http } from '@app/api'

import { setupHttp } from '@/lib/http'

const state = vi.hoisted(() => ({
  token: 'old' as string | null,
  generation: 1,
  csrf: null as string | null,
  client: 'mobile' as 'mobile' | 'web',
  refresh: vi.fn(),
  end: vi.fn()
}))
vi.mock('@/features/auth/session', () => ({
  session: {
    get accessToken() {
      return state.token
    },
    get isActive() {
      return state.token !== null || state.csrf !== null
    },
    get csrfToken() {
      return state.csrf
    },
    get generation() {
      return state.generation
    },
    refresh: state.refresh,
    end: state.end
  }
}))

vi.mock('@/features/auth/session/client', () => ({
  getAuthClient: () => state.client
}))

setupHttp()

function ok(config: InternalAxiosRequestConfig) {
  return {
    config,
    status: 200,
    statusText: 'OK',
    data: { ok: true },
    headers: new AxiosHeaders()
  }
}

function unauthorized(config: InternalAxiosRequestConfig) {
  return new AxiosError('unauthorized', 'ERR_BAD_REQUEST', config, undefined, {
    ...ok(config),
    status: 401,
    statusText: 'Unauthorized'
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  state.token = 'old'
  state.generation = 1
  state.csrf = null
  state.client = 'mobile'
  state.refresh.mockImplementation(async () => {
    state.token = 'new'
  })
  state.end.mockImplementation(async () => {
    state.token = null
    state.generation += 1
  })
})

it('после 401 обновляет токен и повторяет запрос только один раз', async () => {
  const adapter = vi.fn(async (config: InternalAxiosRequestConfig) => {
    if (config.headers.get('Authorization') === 'Bearer old')
      throw unauthorized(config)
    return ok(config)
  })
  http.defaults.adapter = adapter
  await http.get('/api/v1/workspaces')
  expect(state.refresh).toHaveBeenCalledTimes(1)
  expect(adapter).toHaveBeenCalledTimes(2)
  expect(adapter.mock.lastCall?.[0].headers.get('Authorization')).toBe(
    'Bearer new'
  )
})

it('ошибка пароля не запускает refresh', async () => {
  http.defaults.adapter = async config => {
    throw unauthorized(config)
  }
  await expect(http.post('/api/v1/auth/login', {})).rejects.toBeDefined()
  expect(state.refresh).not.toHaveBeenCalled()
  expect(state.end).not.toHaveBeenCalled()
})

it('не возвращает успешный ответ старой сессии после выхода', async () => {
  http.defaults.adapter = async config => {
    state.generation += 1
    return ok(config)
  }
  await expect(http.get('/api/v1/workspaces')).rejects.toThrow(
    'Сессия изменилась'
  )
})

it('повторный 401 завершает сессию без бесконечного цикла', async () => {
  const adapter = vi.fn(async (config: InternalAxiosRequestConfig) => {
    throw unauthorized(config)
  })
  http.defaults.adapter = adapter
  await expect(http.get('/api/v1/workspaces')).rejects.toBeDefined()
  expect(adapter).toHaveBeenCalledTimes(2)
  expect(state.end).toHaveBeenCalledTimes(1)
})

it('старый ответ 403 после выхода отменяется вместо запроса подтверждения', async () => {
  http.defaults.adapter = async config => {
    state.generation += 1
    throw new AxiosError('step up', 'ERR_BAD_REQUEST', config, undefined, {
      ...ok(config),
      status: 403,
      data: { code: 'step_up_required' }
    })
  }
  await expect(http.post('/api/v1/stores', {})).rejects.toMatchObject({
    code: 'ERR_CANCELED'
  })
  expect(state.refresh).not.toHaveBeenCalled()
})

it('запрос после выхода не отправляет старый Authorization', async () => {
  state.token = null
  const adapter = vi.fn(async (config: InternalAxiosRequestConfig) =>
    ok(config)
  )
  http.defaults.adapter = adapter
  await http.get('/api/v1/workspaces', {
    headers: { Authorization: 'Bearer previous-account' }
  })
  expect(
    adapter.mock.lastCall?.[0].headers.get('Authorization')
  ).toBeUndefined()
})

it('браузер отправляет cookies и CSRF вместо Authorization', async () => {
  state.client = 'web'
  state.token = null
  state.csrf = 'test-csrf'
  const adapter = vi.fn(async (config: InternalAxiosRequestConfig) =>
    ok(config)
  )
  http.defaults.adapter = adapter
  await http.post('/api/v1/auth/mfa/send', {})
  const config = adapter.mock.lastCall?.[0]
  expect(config?.withCredentials).toBe(true)
  expect(config?.headers.get('X-CSRF-Token')).toBe('test-csrf')
  expect(config?.headers.has('Authorization')).toBe(false)
})

it('обновляет cookie-сессию при 401 даже без Bearer-токена', async () => {
  state.client = 'web'
  state.token = null
  state.csrf = 'old-csrf'
  state.refresh.mockImplementation(async () => {
    state.csrf = 'new-csrf'
  })
  let attempts = 0
  http.defaults.adapter = async config => {
    if (++attempts === 1) throw unauthorized(config)
    return ok(config)
  }
  await http.get('/api/v1/workspaces')
  expect(state.refresh).toHaveBeenCalledOnce()
  expect(attempts).toBe(2)
})
