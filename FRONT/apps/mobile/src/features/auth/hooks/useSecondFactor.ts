import { useRef, useState } from 'react'

import { type ChallengeResponse, authMfaSend, authMfaVerify } from '@app/api'

import { useCountdown } from '@/hooks/useCountdown'

import { retryAfterSeconds } from '@/lib/errors'

import type { CodeChannel } from '../model/channels'
import { useAuth } from '../providers/AuthProvider'

const CHANNELS: CodeChannel[] = ['telegram', 'sms', 'email']

/**
 * Второй шаг входа. Код обычно уже отправлен сервером при вводе пароля.
 * После перезапуска приложения сведений о нём нет — тогда код запрашивается заново.
 */
export function useSecondFactor() {
  const { secondFactor, user, startSession, signOut } = useAuth()
  const [challenge, setChallenge] = useState<ChallengeResponse | null>(
    secondFactor?.challenge ?? null
  )

  const [deliveryError, setDeliveryError] = useState(
    secondFactor?.delivery_error
  )
  const [isSending, setIsSending] = useState(false)
  const pendingSend = useRef<Promise<number> | null>(null)
  // Неудавшаяся автоматическая отправка уже могла израсходовать попытку на бэке.
  const countdown = useCountdown(
    secondFactor?.challenge?.resend_after ??
      (secondFactor?.delivery_error ? 60 : 0)
  )

  const available = secondFactor?.available ?? []
  const usesAuthenticator =
    !challenge && (available.includes('totp') || !!user?.totp_enabled)
  const otherChannels = CHANNELS.filter(
    channel => available.includes(channel) && channel !== challenge?.channel
  )

  function send(channel?: CodeChannel): Promise<number> {
    if (pendingSend.current) return pendingSend.current
    setIsSending(true)
    const operation = authMfaSend(channel ? { channel } : {})
      .then(next => {
        setChallenge(next)
        setDeliveryError(null)
        countdown.restart(next.resend_after)
        return next.resend_after
      })
      .catch(error => {
        countdown.restart(retryAfterSeconds(error) || 60)
        throw error
      })
      .finally(() => {
        pendingSend.current = null
        setIsSending(false)
      })
    pendingSend.current = operation
    return operation
  }

  async function verify(code: string) {
    await startSession(await authMfaVerify({ code }))
  }

  return {
    challenge,
    usesAuthenticator,
    /** Код не ушёл автоматически или неизвестно, куда он отправлен. */
    needsSending: !challenge && !usesAuthenticator,
    deliveryError,
    isSending,
    retryAfter: countdown.remaining,
    otherChannels,
    canUseRecovery:
      available.includes('recovery') ||
      (available.length === 0 && !!user?.strong_factor_enabled),
    send,
    verify,
    signOut
  }
}
