'use client'

import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation } from '@tanstack/react-query'
import { ArrowLeft, Check, Eye, EyeOff } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'
import { useForm } from 'react-hook-form'

import {
  type ForgotPasswordValues,
  type ResetPasswordValues,
  type SignInValues,
  type SignUpValues,
  forgotPasswordSchema,
  resetPasswordSchema,
  signInSchema,
  signUpSchema
} from '@app/schemas'

import {
  type ChallengeResponse,
  authLogin,
  authPasswordForgot,
  authPasswordReset,
  authRegister,
  authRegisterResend,
  authRegisterVerify
} from '@app/api'

import { ErrorNotice } from '@/components/feedback'
import { Logo } from '@/components/logo'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

import { usePendingInvite } from '@/features/team/pending-invite'

import { errorMessage } from '@/lib/errors'

import { useAuth } from './auth-provider'
import { CodeForm } from './code-form'

export function AuthFrame({ children }: { children: React.ReactNode }) {
  return (
    <main className='auth-page'>
      <aside className='auth-story'>
        <Logo />
        <div className='auth-story-copy'>
          <span className='eyebrow'>ВАШ БИЗНЕС. ЯСНАЯ КАРТИНА.</span>
          <h2>
            Все магазины.
            <br />
            Один взгляд.
          </h2>
          <p>
            Продажи, финансы и остатки
            <br />
            Wildberries и Ozon в одном месте.
          </p>
          <div className='marketplace-tags'>
            <span>Wildberries</span>
            <span>Ozon</span>
          </div>
        </div>
      </aside>
      <section className='auth-panel'>
        <div className='auth-mobile-logo'>
          <Logo />
        </div>
        <div className='auth-form-wrap'>{children}</div>
      </section>
    </main>
  )
}
function Field({
  label,
  error,
  children
}: {
  label: string
  error?: string
  children: React.ReactNode
}) {
  return (
    <label className='field'>
      <span>{label}</span>
      {children}
      {error && <span className='field-error'>{error}</span>}
    </label>
  )
}
function PasswordInput(props: React.ComponentProps<typeof Input>) {
  const [visible, setVisible] = useState(false)
  return (
    <span className='password-field'>
      <Input
        {...props}
        type={visible ? 'text' : 'password'}
      />
      <button
        type='button'
        onClick={() => setVisible(!visible)}
        aria-label={visible ? 'Скрыть пароль' : 'Показать пароль'}
      >
        {visible ? <EyeOff size={18} /> : <Eye size={18} />}
      </button>
    </span>
  )
}
export function AuthScreen({
  mode = 'login'
}: {
  mode?: 'login' | 'register' | 'forgot'
}) {
  const router = useRouter()
  return (
    <AuthFrame>
      {mode === 'login' ? (
        <Login
          onRegister={() => router.push('/register')}
          onForgot={() => router.push('/forgot-password')}
        />
      ) : mode === 'register' ? (
        <Register onBack={() => router.push('/login')} />
      ) : (
        <Forgot onBack={() => router.push('/login')} />
      )}
    </AuthFrame>
  )
}
function Login({
  onRegister,
  onForgot
}: {
  onRegister: () => void
  onForgot: () => void
}) {
  const { accept } = useAuth()
  const invite = usePendingInvite()
  const form = useForm<SignInValues>({
    resolver: zodResolver(signInSchema),
    defaultValues: { email: invite.details?.email ?? '', password: '' }
  })
  useEffect(() => {
    if (invite.details?.email && !form.getValues('email'))
      form.setValue('email', invite.details.email)
  }, [invite.details?.email, form])
  const login = useMutation({
    mutationFn: async () => {
      try {
        await accept(
          await authLogin({
            ...signInSchema.parse(form.getValues()),
            client: 'web'
          })
        )
      } catch (error) {
        throw new Error(errorMessage(error))
      }
    },
    gcTime: 0,
    retry: false
  })
  return (
    <>
      <span className='eyebrow'>ДОБРО ПОЖАЛОВАТЬ</span>
      <h1>Рады видеть вас</h1>

      <form
        className='form-stack'
        onSubmit={form.handleSubmit(() => login.mutate())}
      >
        <Field
          label='Email или телефон'
          error={form.formState.errors.email?.message}
        >
          <Input
            {...form.register('email')}
            autoComplete='username'
            placeholder='you@company.ru'
            aria-invalid={!!form.formState.errors.email}
          />
        </Field>
        <Field
          label='Пароль'
          error={form.formState.errors.password?.message}
        >
          <PasswordInput
            {...form.register('password')}
            autoComplete='current-password'
            aria-invalid={!!form.formState.errors.password}
          />
        </Field>
        <button
          type='button'
          className='text-link self-end'
          disabled={login.isPending}
          onClick={onForgot}
        >
          Забыли пароль?
        </button>
        <ErrorNotice error={login.error} />
        <Button
          type='submit'
          disabled={login.isPending}
          className='w-full'
        >
          {login.isPending ? 'Входим…' : 'Войти'}
        </Button>
      </form>
      <p className='auth-switch'>
        Нет аккаунта?{' '}
        <button
          disabled={login.isPending}
          onClick={onRegister}
          className='text-link'
        >
          Создать
        </button>
      </p>
    </>
  )
}
function Register({ onBack }: { onBack: () => void }) {
  const { accept } = useAuth()
  const invite = usePendingInvite()
  const [challenge, setChallenge] = useState<ChallengeResponse>()
  const form = useForm<SignUpValues>({
    resolver: zodResolver(signUpSchema),
    defaultValues: {
      email: invite.details?.email ?? '',
      password: '',
      workspace_name: invite.code ? 'Команда' : ''
    }
  })
  useEffect(() => {
    if (invite.details?.email && !form.getValues('email'))
      form.setValue('email', invite.details.email)
  }, [invite.details?.email, form])
  const register = useMutation({
    mutationFn: async () => {
      try {
        return await authRegister({
          ...signUpSchema.parse(form.getValues()),
          client: 'web',
          invite_code: invite.code ?? undefined
        })
      } catch (error) {
        throw new Error(errorMessage(error))
      }
    },
    onSuccess: challenge => {
      setChallenge(challenge)
      form.resetField('password')
    },
    gcTime: 0,
    retry: false
  })
  return (
    <>
      <button
        className='back-link'
        onClick={onBack}
      >
        <ArrowLeft size={16} />
        Ко входу
      </button>
      <h1>{challenge ? 'Проверьте почту' : 'Начнём знакомство'}</h1>
      <p className='auth-subtitle'>
        {challenge
          ? 'Подтвердите адрес, чтобы создать аккаунт.'
          : 'Создайте аккаунт для ваших магазинов.'}
      </p>
      {challenge ? (
        <CodeForm
          destination={challenge.destination}
          seconds={challenge.resend_after}
          onVerify={async code =>
            accept(
              await authRegisterVerify({
                challenge_id: challenge.challenge_id,
                code,
                client: 'web'
              })
            )
          }
          onResend={async () => {
            const next = await authRegisterResend({
              challenge_id: challenge.challenge_id
            })
            setChallenge(next)
            return next.resend_after
          }}
        />
      ) : (
        <form
          className='form-stack'
          onSubmit={form.handleSubmit(() => register.mutate())}
        >
          {!invite.code && (
            <Field
              label='Название компании'
              error={form.formState.errors.workspace_name?.message}
            >
              <Input
                {...form.register('workspace_name')}
                autoComplete='organization'
                placeholder='Например, Мой бизнес'
              />
            </Field>
          )}
          <Field
            label='Email'
            error={form.formState.errors.email?.message}
          >
            <Input
              {...form.register('email')}
              type='email'
              autoComplete='email'
              placeholder='you@company.ru'
            />
          </Field>
          <Field
            label='Пароль · от 15 символов'
            error={form.formState.errors.password?.message}
          >
            <PasswordInput
              {...form.register('password')}
              autoComplete='new-password'
            />
          </Field>
          <ErrorNotice error={register.error} />
          <Button
            type='submit'
            disabled={register.isPending}
          >
            {register.isPending ? 'Отправляем код…' : 'Продолжить'}
          </Button>
        </form>
      )}
    </>
  )
}
function Forgot({ onBack }: { onBack: () => void }) {
  const [challenge, setChallenge] = useState<ChallengeResponse>()
  const [done, setDone] = useState(false)
  const email = useForm<ForgotPasswordValues>({
    resolver: zodResolver(forgotPasswordSchema),
    defaultValues: { email: '' }
  })
  const password = useForm<ResetPasswordValues>({
    resolver: zodResolver(resetPasswordSchema),
    defaultValues: { new_password: '' }
  })
  const request = useMutation({
    mutationFn: (values: ForgotPasswordValues) => authPasswordForgot(values),
    onSuccess: setChallenge
  })
  return (
    <>
      <button
        className='back-link'
        onClick={onBack}
      >
        <ArrowLeft size={16} />
        Ко входу
      </button>
      <h1>{done ? 'Пароль изменён' : 'Восстановление доступа'}</h1>
      <p className='auth-subtitle'>
        {done ? 'Войдите с новым паролем.' : 'Пришлём код на почту аккаунта.'}
      </p>
      {done ? (
        <Button onClick={onBack}>
          <Check size={17} />
          Перейти ко входу
        </Button>
      ) : challenge ? (
        <>
          <Field
            label='Новый пароль · от 15 символов'
            error={password.formState.errors.new_password?.message}
          >
            <PasswordInput
              {...password.register('new_password')}
              autoComplete='new-password'
            />
          </Field>
          <CodeForm
            seconds={challenge.resend_after}
            onVerify={async code => {
              const valid = await password.trigger()
              if (!valid) throw new Error('Проверьте новый пароль.')
              await authPasswordReset({
                challenge_id: challenge.challenge_id,
                code,
                new_password: password.getValues('new_password')
              })
              setDone(true)
            }}
            onResend={async () => {
              const next = await authPasswordForgot(email.getValues())
              setChallenge(next)
              return next.resend_after
            }}
          />
        </>
      ) : (
        <form
          className='form-stack'
          onSubmit={email.handleSubmit(values => request.mutate(values))}
        >
          <Field
            label='Email'
            error={email.formState.errors.email?.message}
          >
            <Input
              {...email.register('email')}
              type='email'
              autoComplete='email'
            />
          </Field>
          <ErrorNotice error={request.error} />
          <Button
            type='submit'
            disabled={request.isPending}
          >
            {request.isPending ? 'Отправляем…' : 'Получить код'}
          </Button>
        </form>
      )}
    </>
  )
}
