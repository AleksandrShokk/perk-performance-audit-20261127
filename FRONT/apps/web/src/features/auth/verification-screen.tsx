'use client'

import { useMutation } from '@tanstack/react-query'
import { ShieldCheck } from 'lucide-react'
import { useState } from 'react'

import { authMfaSend, authMfaVerify } from '@app/api'

import { ErrorNotice } from '@/components/feedback'
import { Button } from '@/components/ui/button'

import { useAuth } from './auth-provider'
import { AuthFrame } from './auth-screen'
import { CodeForm } from './code-form'

export function VerificationScreen() {
  const { user, secondFactor, accept, signOut } = useAuth()
  const [recovery, setRecovery] = useState(false)
  const [challenge, setChallenge] = useState(
    secondFactor?.challenge ?? undefined
  )
  const send = useMutation({
    mutationFn: () => authMfaSend({}),
    onSuccess: setChallenge
  })
  const verify = useMutation({
    mutationFn: async (code: string) => accept(await authMfaVerify({ code }))
  })
  const exit = useMutation({ mutationFn: signOut })
  const authenticator =
    !challenge &&
    (user?.totp_enabled || secondFactor?.available.includes('totp'))
  return (
    <AuthFrame>
      <div className='auth-icon'>
        <ShieldCheck size={24} />
      </div>
      <h1>Подтвердите вход</h1>
      <p className='auth-subtitle'>
        {recovery
          ? 'Введите один из сохранённых резервных кодов.'
          : authenticator
            ? 'Введите код из приложения-аутентификатора.'
            : challenge
              ? `Код отправлен: ${challenge.destination}`
              : 'Получите код для подтверждения входа.'}
      </p>
      {challenge || authenticator || recovery ? (
        <CodeForm
          key={recovery ? 'recovery' : (challenge?.challenge_id ?? 'totp')}
          recovery={recovery}
          label={recovery ? 'Резервный код' : 'Код подтверждения'}
          seconds={challenge?.resend_after ?? 0}
          onVerify={verify.mutateAsync}
          onResend={
            authenticator || recovery
              ? undefined
              : async () => (await send.mutateAsync()).resend_after
          }
        />
      ) : (
        <Button
          className='w-full'
          disabled={send.isPending}
          onClick={() => send.mutate()}
        >
          {send.isPending ? 'Отправляем…' : 'Получить код'}
        </Button>
      )}
      <ErrorNotice error={send.error ?? exit.error} />
      {(user?.strong_factor_enabled ||
        secondFactor?.available.includes('recovery')) && (
        <button
          className='text-link auth-secondary'
          disabled={verify.isPending || send.isPending}
          onClick={() => setRecovery(!recovery)}
        >
          {recovery ? 'Ввести обычный код' : 'Использовать резервный код'}
        </button>
      )}
      <button
        className='muted auth-secondary'
        disabled={exit.isPending || verify.isPending || send.isPending}
        onClick={() => exit.mutate()}
      >
        Войти в другой аккаунт
      </button>
    </AuthFrame>
  )
}

export { PhoneEnrollment } from './phone-enrollment'
