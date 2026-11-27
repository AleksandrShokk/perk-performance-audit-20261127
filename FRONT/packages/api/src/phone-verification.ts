'use client'

import { useRef, useState } from 'react'

import {
  authPhoneChangeSend,
  authPhoneChangeVerify,
  authPhoneConfirm,
  authPhoneStart
} from './generated/endpoints/authentication/authentication'
import type {
  ChallengeResponse,
  RecoveryCodesResponse
} from './generated/models'

type Channel = 'telegram' | 'email'
type Step =
  | { kind: 'number' }
  | { kind: 'previous'; phone: string; challenge: ChallengeResponse }
  | { kind: 'authorized'; phone: string; authorizationId: string }
  | {
      kind: 'new'
      phone: string
      challenge: ChallengeResponse
      authorizationId?: string
    }

/** One phone flow for the website and the app. Grants live only in component memory. */
export function usePhoneVerification({
  changing,
  initialAction,
  onComplete
}: {
  changing: boolean
  initialAction: <T>(action: () => Promise<T>) => Promise<T>
  onComplete: (result: RecoveryCodesResponse) => Promise<void>
}) {
  const [step, setStep] = useState<Step>({ kind: 'number' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const pending = useRef(false)

  async function run<T>(action: () => Promise<T>, reportError = true) {
    if (pending.current)
      throw new Error('Дождитесь завершения текущего действия.')
    pending.current = true
    setBusy(true)
    setError(null)
    try {
      return await action()
    } catch (failure) {
      if (reportError) setError(failure)
      throw failure
    } finally {
      pending.current = false
      setBusy(false)
    }
  }

  async function sendNew(phone: string, authorizationId?: string) {
    const request = () =>
      authPhoneStart({
        phone,
        channel: 'telegram',
        authorization_id: authorizationId
      })
    const challenge = await (changing ? request() : initialAction(request))
    setStep({ kind: 'new', phone, challenge, authorizationId })
    return challenge.resend_after
  }

  async function sendPrevious(phone: string, channel: Channel) {
    const challenge = await authPhoneChangeSend({ phone, channel })
    setStep({ kind: 'previous', phone, challenge })
    return challenge.resend_after
  }

  return {
    step,
    busy,
    error,
    start: (phone: string, channel: Channel = 'telegram') =>
      run(() => (changing ? sendPrevious(phone, channel) : sendNew(phone))),
    useEmail: () =>
      run(() => {
        if (step.kind !== 'previous')
          throw new Error('Начните смену номера заново.')
        return sendPrevious(step.phone, 'email')
      }),
    verify: (code: string) =>
      run(async () => {
        if (step.kind === 'previous') {
          const grant = await authPhoneChangeVerify({
            challenge_id: step.challenge.challenge_id,
            code
          })
          // Preserve the grant if sending to the new phone fails: the user can retry safely.
          setStep({
            kind: 'authorized',
            phone: step.phone,
            authorizationId: grant.authorization_id
          })
          try {
            await sendNew(step.phone, grant.authorization_id)
          } catch (failure) {
            setError(failure)
            throw failure
          }
        } else if (step.kind === 'new') {
          const action = () => authPhoneConfirm({ code })
          await onComplete(await (changing ? action() : initialAction(action)))
        }
      }, false),
    resend: () =>
      run(() => {
        if (step.kind === 'previous')
          return sendPrevious(step.phone, step.challenge.channel as Channel)
        if (step.kind === 'new' || step.kind === 'authorized')
          return sendNew(step.phone, step.authorizationId)
        throw new Error('Сначала введите номер телефона.')
      }),
    reset: () => {
      if (pending.current) return
      setStep({ kind: 'number' })
      setError(null)
    }
  }
}
