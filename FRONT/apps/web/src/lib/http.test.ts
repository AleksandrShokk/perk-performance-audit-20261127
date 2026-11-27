import {
  AxiosError,
  AxiosHeaders,
  type InternalAxiosRequestConfig
} from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { http } from '@app/api'

import { createSessionTransport } from './http'

let cookie = 'perk_csrf=pc_old'
beforeEach(() => {
  http.interceptors.request.clear()
  http.interceptors.response.clear()
  cookie = 'perk_csrf=pc_old'
  vi.stubGlobal('document', {
    get cookie() {
      return cookie
    },
    set cookie(value: string) {
      cookie = value.includes('Max-Age=0') ? '' : value
    }
  })
})
afterEach(() => vi.unstubAllGlobals())
function response(
  config: InternalAxiosRequestConfig,
  data: unknown,
  status = 200
) {
  return { config, data, status, statusText: '', headers: new AxiosHeaders() }
}

describe('browser session transport', () => {
  it('adds CSRF to writes and keeps access tokens out of JavaScript headers', async () => {
    const session = createSessionTransport()
    session.install()
    http.defaults.adapter = async config => {
      expect(config.withCredentials).toBe(true)
      expect(config.headers.get('X-CSRF-Token')).toBe('pc_old')
      expect(config.headers.get('Authorization')).toBeUndefined()
      return response(config, { ok: true })
    }
    await http.post('/api/v1/workspaces/test/stores', {})
  })
  it('rotates only once for concurrent expired requests', async () => {
    const session = createSessionTransport()
    session.install()
    let refreshes = 0
    const attempts = new Map<string, number>()
    http.defaults.adapter = async config => {
      if (config.url?.endsWith('/auth/refresh')) {
        refreshes++
        await new Promise(resolve => setTimeout(resolve, 15))
        cookie = 'perk_csrf=pc_new'
        return response(config, {
          csrf_token: 'pc_new',
          expires_in: 900,
          mfa_required: false
        })
      }
      const key = config.url!
      attempts.set(key, (attempts.get(key) ?? 0) + 1)
      if (attempts.get(key) === 1)
        throw new AxiosError(
          'expired',
          'ERR_BAD_REQUEST',
          config,
          undefined,
          response(config, {}, 401)
        )
      return response(config, { ok: true })
    }
    const values = await Promise.all([
      http.get('/api/v1/report/a'),
      http.get('/api/v1/report/b')
    ])
    expect(refreshes).toBe(1)
    expect(values.every(value => value.data.ok)).toBe(true)
  })
  it('rejects late data after sign out and notifies cache owners', async () => {
    const session = createSessionTransport()
    session.install()
    const ended = vi.fn()
    session.subscribe(ended)
    let release!: () => void
    const blocked = new Promise<void>(resolve => {
      release = resolve
    })
    http.defaults.adapter = async config => {
      await blocked
      return response(config, { private: 'old-account' })
    }
    const request = http.get('/api/v1/report/private')
    await Promise.resolve()
    session.end()
    release()
    await expect(request).rejects.toMatchObject({ code: 'ERR_CANCELED' })
    expect(ended).toHaveBeenCalledOnce()
    expect(cookie).toBe('')
  })
  it('does not refresh for an incorrect password', async () => {
    const session = createSessionTransport()
    session.install()
    const requests: string[] = []
    http.defaults.adapter = async config => {
      requests.push(config.url!)
      throw new AxiosError(
        'invalid',
        'ERR_BAD_REQUEST',
        config,
        undefined,
        response(config, {}, 401)
      )
    }
    await expect(http.post('/api/v1/auth/login', {})).rejects.toBeInstanceOf(
      AxiosError
    )
    expect(requests).toEqual(['/api/v1/auth/login'])
  })
})
