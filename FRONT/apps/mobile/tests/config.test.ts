import { afterEach, beforeEach, expect, it, vi } from 'vitest'

beforeEach(() => {
  vi.resetModules()
  vi.stubEnv('EXPO_PUBLIC_API_URL', 'http://api.test/api/v1')
})
afterEach(() => {
  vi.stubGlobal('__DEV__', true)
  vi.unstubAllEnvs()
})

it('release refuses a plain HTTP API', async () => {
  vi.stubGlobal('__DEV__', false)
  await expect(import('@/lib/config')).rejects.toThrow('HTTPS')
})
it('release accepts HTTPS and normalizes the base path', async () => {
  vi.stubGlobal('__DEV__', false)
  vi.stubEnv('EXPO_PUBLIC_API_URL', 'https://api.test/api/v1/')
  expect((await import('@/lib/config')).apiOrigin).toBe('https://api.test')
})
it('development still permits a local phone connection', async () => {
  vi.stubGlobal('__DEV__', true)
  expect((await import('@/lib/config')).apiOrigin).toBe('http://api.test')
})
