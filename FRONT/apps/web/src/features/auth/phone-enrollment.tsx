'use client'

import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation } from '@tanstack/react-query'
import { Check, Copy, ShieldCheck } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useState } from 'react'
import { useForm } from 'react-hook-form'

import {
  type PhoneValues,
  TELEGRAM_PHONE_NOTICE,
  formatPhoneInput,
  phoneSchema
} from '@app/schemas'

import { usePhoneVerification } from '@app/api'

import { ErrorNotice } from '@/components/feedback'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

import { useAuth } from './auth-provider'
import { AuthFrame } from './auth-screen'
import { CodeForm } from './code-form'
import { useStepUp } from './step-up-provider'

export function PhoneEnrollment() {
  const router = useRouter()
  const { user, reload, signOut } = useAuth()
  const changing = !!user?.phone
  const [codes, setCodes] = useState<string[]>()
  const [copied, setCopied] = useState(false)
  const [copyError, setCopyError] = useState<unknown>(null)
  const withStepUp = useStepUp()
  const form = useForm<PhoneValues>({
    resolver: zodResolver(phoneSchema),
    defaultValues: { phone: '+', channel: 'telegram' }
  })
  async function finish() {
    await reload()
    router.replace(changing ? '/settings/profile' : '/')
  }
  const flow = usePhoneVerification({
    changing,
    initialAction: withStepUp,
    onComplete: async result => {
      if (result.recovery_codes?.length) setCodes(result.recovery_codes)
      else await finish()
    }
  })
  async function copyCodes() {
    if (!codes) return
    setCopyError(null)
    try {
      await navigator.clipboard.writeText(codes.join('\n'))
      setCopied(true)
    } catch {
      setCopyError(
        new Error('Не удалось скопировать. Выделите и сохраните коды вручную.')
      )
    }
  }
  const exit = useMutation({ mutationFn: signOut })
  const step = flow.step
  const challenge =
    step.kind === 'previous' || step.kind === 'new' ? step.challenge : null
  return (
    <AuthFrame>
      <div className='auth-icon'>
        <ShieldCheck size={24} />
      </div>
      <h1>
        {codes
          ? 'Сохраните резервные коды'
          : step.kind === 'previous'
            ? 'Подтвердите смену номера'
            : step.kind === 'new' || step.kind === 'authorized'
              ? 'Подтвердите новый номер'
              : changing
                ? 'Смена номера'
                : 'Защитите аккаунт'}
      </h1>
      <p className='auth-subtitle'>
        {codes
          ? 'Они помогут войти, если телефон будет недоступен.'
          : step.kind === 'previous'
            ? challenge?.channel === 'email'
              ? 'Код отправлен на вашу почту.'
              : `Код отправлен в Telegram на старый номер ${user?.phone}.`
            : changing && step.kind === 'number'
              ? `Сейчас привязан ${user?.phone}. Сначала подтвердим старый номер, затем новый.`
              : TELEGRAM_PHONE_NOTICE}
      </p>
      {codes ? (
        <div className='form-stack'>
          <pre className='recovery-codes'>{codes.join('\n')}</pre>
          <Button
            variant='secondary'
            onClick={() => void copyCodes()}
          >
            {copied ? <Check size={17} /> : <Copy size={17} />}
            {copied ? 'Все коды скопированы' : 'Скопировать все коды'}
          </Button>
          <Button onClick={() => void finish()}>Продолжить</Button>
        </div>
      ) : challenge ? (
        <div className='form-stack'>
          <CodeForm
            key={challenge.challenge_id}
            destination={`Код отправлен: ${challenge.destination}`}
            seconds={challenge.resend_after}
            onVerify={flow.verify}
            onResend={flow.resend}
            disabled={flow.busy}
          />
          {step.kind === 'previous' && challenge.channel === 'telegram' && (
            <Button
              variant='ghost'
              disabled={flow.busy}
              onClick={() => {
                void flow.useEmail().catch(() => {})
              }}
            >
              Нет доступа к старому номеру — код на почту
            </Button>
          )}
          <Button
            variant='ghost'
            disabled={flow.busy}
            onClick={flow.reset}
          >
            Ввести другой номер
          </Button>
        </div>
      ) : step.kind === 'authorized' ? (
        <div className='form-stack'>
          <Button
            disabled={flow.busy}
            onClick={() => {
              void flow.resend().catch(() => {})
            }}
          >
            {flow.busy ? 'Отправляем…' : 'Отправить код на новый номер'}
          </Button>
          <Button
            variant='ghost'
            disabled={flow.busy}
            onClick={flow.reset}
          >
            Начать заново
          </Button>
        </div>
      ) : (
        <form
          className='form-stack'
          onSubmit={form.handleSubmit(async values => {
            try {
              await flow.start(values.phone)
            } catch {
              /* Error is shown below. */
            }
          })}
        >
          <label className='field'>
            <span>{changing ? 'Новый номер телефона' : 'Номер телефона'}</span>
            <Input
              {...form.register('phone')}
              type='tel'
              autoComplete='tel'
              placeholder='+7 900 123-45-67'
              maxLength={32}
              disabled={flow.busy}
              onChange={event =>
                form.setValue('phone', formatPhoneInput(event.target.value), {
                  shouldDirty: true
                })
              }
            />
            {form.formState.errors.phone && (
              <span className='field-error'>
                {form.formState.errors.phone.message}
              </span>
            )}
          </label>
          {changing && <p className='muted'>{TELEGRAM_PHONE_NOTICE}</p>}
          <Button
            disabled={flow.busy}
            type='submit'
          >
            {flow.busy ? 'Отправляем…' : 'Получить код'}
          </Button>
          {changing && (
            <Button
              type='button'
              variant='ghost'
              disabled={flow.busy}
              onClick={() => {
                void form.handleSubmit(async values => {
                  try {
                    await flow.start(values.phone, 'email')
                  } catch {
                    /* Error is shown below. */
                  }
                })()
              }}
            >
              Нет доступа к старому номеру — код на почту
            </Button>
          )}
        </form>
      )}
      <ErrorNotice error={flow.error ?? exit.error ?? copyError} />
      <button
        className='muted auth-secondary'
        disabled={exit.isPending || flow.busy}
        onClick={() => exit.mutate()}
      >
        Выйти из аккаунта
      </button>
    </AuthFrame>
  )
}
