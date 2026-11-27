import { beforeEach, describe, expect, it, vi } from 'vitest'

import { session } from '@/features/auth/session/session'

const mock = vi.hoisted(() => ({
  read: vi.fn(),
  write: vi.fn(),
  remove: vi.fn(),
  refresh: vi.fn()
}))
vi.mock('@app/api', () => ({ authRefresh: mock.refresh }))
vi.mock('@/features/auth/session/tokenStorage', () => ({
  readTokens: mock.read,
  writeTokens: mock.write,
  deleteTokens: mock.remove
}))

const response = (token: string) => ({
  access_token: token,
  refresh_token: `${token}-refresh`,
  expires_in: 300,
  mfa_required: false
})

beforeEach(async () => {
  vi.clearAllMocks()
  mock.write.mockResolvedValue(undefined)
  mock.remove.mockResolvedValue(undefined)
  await session.end()
})

describe('сессия', () => {
  it('читает токены из защищённого хранилища', async () => {
    mock.read.mockResolvedValue({ accessToken: 'a', refreshToken: 'r' })
    expect(await session.restore()).toBe(true)
    expect(session.accessToken).toBe('a')
  })
  it('параллельные 401 используют один refresh', async () => {
    await session.start(response('old'))
    mock.refresh.mockResolvedValue(response('new'))
    await Promise.all([session.refresh(), session.refresh(), session.refresh()])
    expect(mock.refresh).toHaveBeenCalledTimes(1)
    expect(session.accessToken).toBe('new')
  })
  it('поздний refresh не возвращает сессию после выхода', async () => {
    await session.start(response('old'))
    let finish!: (value: ReturnType<typeof response>) => void
    mock.refresh.mockImplementation(
      () =>
        new Promise(resolve => {
          finish = resolve
        })
    )
    const operation = session.refresh()
    await session.end()
    finish(response('too-late'))
    await operation
    expect(session.accessToken).toBeNull()
    expect(mock.write).toHaveBeenCalledTimes(1)
  })
  it('сетевая ошибка refresh сохраняет сессию', async () => {
    await session.start(response('old'))
    mock.refresh.mockRejectedValue(new Error('offline'))
    await expect(session.refresh()).rejects.toThrow('offline')
    expect(session.accessToken).toBe('old')
  })
  it('неудачная запись уже обновлённых токенов завершает сессию', async () => {
    await session.start(response('old'))
    mock.refresh.mockResolvedValue(response('new'))
    mock.write.mockRejectedValueOnce(new Error('storage unavailable'))
    await expect(session.refresh()).rejects.toThrow('storage unavailable')
    expect(session.accessToken).toBeNull()
  })
})

it('выход дожидается удаления данных подписчиками', async () => {
  await session.start(response('old'))
  let finish!: () => void
  const cleanup = new Promise<void>(resolve => {
    finish = resolve
  })
  const unsubscribe = session.onEnd(() => cleanup)
  try {
    let ended = false
    const operation = session.end().then(() => {
      ended = true
    })
    await Promise.resolve()
    expect(session.accessToken).toBeNull()
    expect(ended).toBe(false)
    finish()
    await operation
    expect(ended).toBe(true)
    expect(mock.remove).toHaveBeenCalled()
  } finally {
    finish()
    unsubscribe()
  }
})

it('обновление новой сессии не ждёт refresh предыдущего аккаунта', async () => {
  await session.start(response('old'))
  let finishOld!: (value: ReturnType<typeof response>) => void
  mock.refresh.mockImplementationOnce(
    () =>
      new Promise(resolve => {
        finishOld = resolve
      })
  )
  const previous = session.refresh()
  await session.end()
  await session.start(response('another-user'))
  mock.refresh.mockResolvedValueOnce(response('another-user-fresh'))
  await session.refresh()
  expect(mock.refresh).toHaveBeenCalledTimes(2)
  expect(session.accessToken).toBe('another-user-fresh')
  finishOld(response('old-late'))
  await previous
  expect(session.accessToken).toBe('another-user-fresh')
})

it('использует подтверждённые токены сразу, пока SecureStore ещё сохраняет их', async () => {
  await session.start(response('limited'))
  let finish!: () => void
  const saving = new Promise<void>(resolve => {
    finish = resolve
  })
  mock.write.mockReturnValueOnce(saving)
  const installing = session.start(response('verified'))
  try {
    expect(session.accessToken).toBe('verified')
  } finally {
    finish()
    await installing
  }
})
