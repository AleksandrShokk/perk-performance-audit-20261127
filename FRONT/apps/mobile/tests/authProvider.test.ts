import type * as React from 'react'
import { beforeEach, expect, it, vi } from 'vitest'

import { AuthProvider } from '@/features/auth/providers/AuthProvider'

const mock = vi.hoisted(() => ({
  token: 'limited',
  generation: 1,
  reset: vi.fn(),
  start: vi.fn(),
  fetch: vi.fn()
}))

vi.mock('react', async importOriginal => {
  const actual = await importOriginal<typeof React>()
  return {
    ...actual,
    useState: (initial: unknown) => [initial, vi.fn()],
    useRef: (value: unknown) => ({ current: value }),
    useEffect: vi.fn()
  }
})
vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({ fetchQuery: mock.fetch })
}))
vi.mock('@app/api', () => ({
  authLogout: vi.fn(),
  getAuthMeQueryKey: () => ['me'],
  getAuthMeQueryOptions: () => ({ queryKey: ['me'] }),
  useAuthMe: () => ({ data: undefined, isError: false })
}))
vi.mock('@/features/auth/session', () => ({
  session: {
    start: mock.start,
    get generation() {
      return mock.generation
    }
  }
}))
vi.mock('@/lib/queryClient', () => ({ resetQueryCache: mock.reset }))

beforeEach(() => {
  vi.clearAllMocks()
  mock.token = 'limited'
  mock.generation = 1
  mock.start.mockImplementation(async (response: { access_token: string }) => {
    mock.token = response.access_token
    return ++mock.generation
  })
  mock.reset.mockImplementation(async () => {
    // Очистка кэша может разбудить подписчика /me: старая сессия после MFA уже отозвана.
    if (mock.token === 'limited') throw new Error('old session revoked')
  })
})

it('после MFA устанавливает новые токены до очистки кэша и повторного /me', async () => {
  const element = AuthProvider({ children: null })
  const { value } = element.props as {
    value: {
      startSession: (response: {
        access_token: string
        refresh_token: string
        expires_in: number
        mfa_required: boolean
      }) => Promise<void>
    }
  }
  await value.startSession({
    access_token: 'verified',
    refresh_token: 'new-refresh',
    expires_in: 300,
    mfa_required: false
  })
  expect(mock.token).toBe('verified')
  expect(mock.reset).toHaveBeenCalledOnce()
  expect(mock.fetch).toHaveBeenCalledOnce()
})

it('выход во время очистки кэша не возобновляет вход', async () => {
  mock.reset.mockImplementation(async () => {
    mock.generation += 1
  })
  const element = AuthProvider({ children: null })
  const { value } = element.props as {
    value: {
      startSession: (response: {
        access_token: string
        refresh_token: string
        expires_in: number
        mfa_required: boolean
      }) => Promise<void>
    }
  }
  await value.startSession({
    access_token: 'verified',
    refresh_token: 'new-refresh',
    expires_in: 300,
    mfa_required: false
  })
  expect(mock.fetch).not.toHaveBeenCalled()
})
