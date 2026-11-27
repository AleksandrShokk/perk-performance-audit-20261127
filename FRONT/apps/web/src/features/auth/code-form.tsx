'use client'

import { useMutation } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import { otpCode, secondFactorCode } from '@app/schemas'

import { ErrorNotice } from '@/components/feedback'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

import { retryAfter } from '@/lib/errors'

type Props = {
  destination?: string
  seconds?: number
  onVerify: (code: string) => Promise<unknown>
  onResend?: () => Promise<number>
  recovery?: boolean
  label?: string
  disabled?: boolean
}
/** A real full-width input: keyboard, autofill and paste all use the same value. */
export function CodeForm({
  destination,
  seconds = 0,
  onVerify,
  onResend,
  recovery,
  label = 'Код подтверждения',
  disabled = false
}: Props) {
  const [code, setCode] = useState('')
  const [validation, setValidation] = useState<string>()
  const [until, setUntil] = useState(() => Date.now() + seconds * 1000)
  const [remaining, setRemaining] = useState(seconds)
  useEffect(() => {
    const update = () =>
      setRemaining(Math.max(0, Math.ceil((until - Date.now()) / 1000)))
    const timer = window.setInterval(update, 1000)
    return () => window.clearInterval(timer)
  }, [until])
  const verify = useMutation({ mutationFn: onVerify })
  const resend = useMutation({
    mutationFn: async () => (onResend ? onResend() : 0),
    onSuccess: delay => {
      setCode('')
      setUntil(Date.now() + delay * 1000)
    },
    onError: error =>
      setUntil(Date.now() + Math.max(retryAfter(error), 60) * 1000)
  })
  const busy = disabled || verify.isPending || resend.isPending
  return (
    <form
      className='form-stack'
      onSubmit={event => {
        event.preventDefault()
        const parsed = (recovery ? secondFactorCode : otpCode).safeParse(code)
        setValidation(
          parsed.success ? undefined : parsed.error.issues[0]?.message
        )
        if (parsed.success && !busy) verify.mutate(parsed.data)
      }}
    >
      {destination && <p className='muted'>{destination}</p>}
      <label className='field'>
        <span>{label}</span>
        <Input
          autoFocus
          name='code'
          value={code}
          onChange={event => {
            setCode(event.target.value)
            setValidation(undefined)
          }}
          autoComplete='one-time-code'
          inputMode={recovery ? 'text' : 'numeric'}
          maxLength={recovery ? 80 : 6}
          className='code-input'
          aria-invalid={!!validation}
          disabled={busy}
        />
        {validation && <span className='field-error'>{validation}</span>}
      </label>
      <ErrorNotice error={verify.error ?? resend.error} />
      <Button
        type='submit'
        disabled={busy}
        className='w-full'
      >
        {verify.isPending ? 'Проверяем…' : 'Подтвердить'}
      </Button>
      {onResend && (
        <Button
          type='button'
          variant='ghost'
          disabled={busy || remaining > 0}
          onClick={() => resend.mutate()}
        >
          {remaining > 0
            ? `Отправить снова через ${remaining} с`
            : 'Отправить код ещё раз'}
        </Button>
      )}
    </form>
  )
}
