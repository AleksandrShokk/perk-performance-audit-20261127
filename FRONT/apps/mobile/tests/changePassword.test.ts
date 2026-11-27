import { beforeEach, expect, it, vi } from 'vitest'

import { changePasswordSchema } from '@app/schemas'

import { useChangePassword } from '@/features/auth/hooks/useChangePassword'

const calls = vi.hoisted(() => ({
  options: vi.fn(),
  change: vi.fn(),
  end: vi.fn(),
  stepUp: vi.fn()
}))
vi.mock('@tanstack/react-query', () => ({
  useMutation: (options: unknown) => {
    calls.options(options)
    return { isPending: false, error: null }
  }
}))
vi.mock('react-hook-form', () => ({
  useForm: () => ({ control: {}, handleSubmit: vi.fn() })
}))
vi.mock('@hookform/resolvers/zod', () => ({ zodResolver: vi.fn() }))
vi.mock('@app/api', () => ({ authChangePassword: calls.change }))
vi.mock('@/features/auth/session', () => ({ session: { end: calls.end } }))
vi.mock('@/features/auth/stepUp/StepUpProvider', () => ({
  useStepUp: () => calls.stepUp
}))

beforeEach(() => {
  vi.clearAllMocks()
  calls.stepUp.mockImplementation((action: () => Promise<unknown>) => action())
})

it('оставляет текущий пароль без обрезки и проверяет политику нового', () => {
  const values = {
    password: '  old secret  ',
    new_password: 'another long password phrase 42'
  }
  expect(changePasswordSchema.parse(values)).toEqual(values)
  expect(
    changePasswordSchema.safeParse({ ...values, new_password: 'short' }).success
  ).toBe(false)
  expect(
    changePasswordSchema.safeParse({ ...values, new_password: 'a'.repeat(20) })
      .success
  ).toBe(false)
})

it('подтверждает смену на сервере перед удалением локальной сессии', async () => {
  useChangePassword()
  const options = calls.options.mock.lastCall![0]
  const values = {
    password: 'old',
    new_password: 'another long password phrase 42'
  }
  await options.mutationFn(values)
  expect(calls.stepUp).toHaveBeenCalledOnce()
  expect(calls.change).toHaveBeenCalledExactlyOnceWith(values)
  expect(calls.end).not.toHaveBeenCalled()
  await options.onSuccess()
  expect(calls.end).toHaveBeenCalledOnce()
})

it('ошибка текущего пароля сохраняет локальную сессию', async () => {
  calls.change.mockRejectedValueOnce(new Error('password_invalid'))
  useChangePassword()
  const options = calls.options.mock.lastCall![0]
  await expect(
    options.mutationFn({
      password: 'wrong',
      new_password: 'another long password phrase 42'
    })
  ).rejects.toThrow('password_invalid')
  expect(calls.end).not.toHaveBeenCalled()
})
