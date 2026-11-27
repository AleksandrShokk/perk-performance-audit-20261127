import { beforeEach, expect, it, vi } from 'vitest'

import { recoveryCode, secondFactorCode } from '@app/schemas'

import { session } from '@/features/auth/session/session'

const mock = vi.hoisted(() => ({ refresh: vi.fn() }))
vi.mock('@app/api', () => ({ authRefresh: mock.refresh }))
vi.mock('@/features/auth/session/client', () => ({
  getAuthClient: () => 'web'
}))
vi.mock(
  '@/features/auth/session/tokenStorage',
  () => import('@/features/auth/session/tokenStorage.web')
)

const response = (csrf: string) => ({
  csrf_token: csrf,
  expires_in: 300,
  mfa_required: false
})
beforeEach(async () => {
  vi.clearAllMocks()
  vi.stubGlobal('document', { cookie: '' })
  await session.end()
  document.cookie = ''
})

it('принимает cookie-сессию без доступных JavaScript токенов', async () => {
  await session.start(response('csrf-only'))
  expect(session.isActive).toBe(true)
  expect(session.accessToken).toBeNull()
  expect(session.csrfToken).toBe('csrf-only')
})

it('восстанавливает отметку сессии из CSRF cookie', async () => {
  document.cookie = 'other=value; perk_csrf=restored-csrf'
  expect(await session.restore()).toBe(true)
  expect(session.csrfToken).toBe('restored-csrf')
  expect(session.accessToken).toBeNull()
})

it('обновляет браузерную сессию через cookies без refresh-токена в JSON', async () => {
  await session.start(response('old-csrf'))
  mock.refresh.mockResolvedValue(response('new-csrf'))
  await session.refresh()
  expect(mock.refresh).toHaveBeenCalledWith({})
  expect(session.csrfToken).toBe('new-csrf')
})

it('не принимает Bearer-токены вместо браузерного CSRF-подтверждения', async () => {
  await expect(
    session.start({
      access_token: 'native',
      refresh_token: 'native-refresh',
      expires_in: 300,
      mfa_required: false
    })
  ).rejects.toThrow('CSRF')
  expect(session.isActive).toBe(false)
})

it('поле резервного кода принимает полный rc_, а шесть цифр остаются отдельным способом', () => {
  const code = 'rc_' + 'a'.repeat(22)
  expect(recoveryCode.parse('  ' + code + '  ')).toBe(code)
  expect(recoveryCode.safeParse('123456').success).toBe(false)
  expect(recoveryCode.safeParse('rc_short').success).toBe(false)
  expect(secondFactorCode.safeParse('123456').success).toBe(true)
})
