import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation } from '@tanstack/react-query'
import { router, useLocalSearchParams } from 'expo-router'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { View } from 'react-native'

import {
  type ForgotPasswordValues,
  type ResetPasswordValues,
  forgotPasswordSchema,
  resetPasswordSchema
} from '@app/schemas'

import {
  type ChallengeResponse,
  authPasswordForgot,
  authPasswordReset
} from '@app/api'

import { Button, CodeInput, FormField, Notice, Text } from '@/components/ui'

import { AuthLayout } from '@/features/auth/components/AuthLayout'
import { FooterLink } from '@/features/auth/components/FooterLink'

import { useCountdown } from '@/hooks/useCountdown'

import { errorMessage, retryAfterSeconds } from '@/lib/errors'

import { createStyles } from '@/theme'

/**
 * Сброс пароля: email → код из письма и новый пароль.
 * Ответ сервера одинаков для любого адреса — экран не раскрывает, есть ли аккаунт.
 * Второй фактор сброс не отменяет: при входе всё равно понадобится код.
 */
export default function ForgotPasswordScreen() {
  const params = useLocalSearchParams<{ email?: string }>()
  const [challenge, setChallenge] = useState<ChallengeResponse | null>(null)
  const [done, setDone] = useState(false)

  const request = useMutation({
    mutationFn: (values: ForgotPasswordValues) => authPasswordForgot(values),
    onSuccess: setChallenge
  })

  return (
    <AuthLayout
      title={done ? 'Пароль изменён' : 'Сброс пароля'}
      subtitle='Пришлём код на почту аккаунта.'
      footer={
        !done ? (
          <FooterLink
            text='Вспомнили пароль?'
            action='Войти'
            href='/sign-in'
          />
        ) : undefined
      }
    >
      {done ? (
        <DoneStep />
      ) : challenge ? (
        <ResetStep
          challenge={challenge}
          // Новый код — новый challenge: onSuccess заменит его в состоянии.
          onResend={async () =>
            (
              await request.mutateAsync(
                request.variables ?? { email: params.email ?? '' }
              )
            ).resend_after
          }
          onDone={() => setDone(true)}
        />
      ) : (
        <EmailStep
          initialEmail={params.email ?? ''}
          pending={request.isPending}
          error={request.error}
          onSubmit={values => request.mutate(values)}
        />
      )}
    </AuthLayout>
  )
}

function EmailStep({
  initialEmail,
  pending,
  error,
  onSubmit
}: {
  initialEmail: string
  pending: boolean
  error: Error | null
  onSubmit: (values: ForgotPasswordValues) => void
}) {
  const styles = useStyles()
  const form = useForm<ForgotPasswordValues>({
    resolver: zodResolver(forgotPasswordSchema),
    defaultValues: { email: initialEmail }
  })
  const submit = form.handleSubmit(onSubmit)
  return (
    <View style={styles.step}>
      <FormField
        control={form.control}
        name='email'
        label='Email'
        placeholder='seller@example.ru'
        keyboardType='email-address'
        autoCapitalize='none'
        autoComplete='email'
        textContentType='emailAddress'
        returnKeyType='send'
        onSubmitEditing={() => void submit()}
      />
      {error && (
        <Notice
          tone='error'
          message={errorMessage(error)}
        />
      )}
      <Button
        title='Получить код'
        loading={pending}
        onPress={() => void submit()}
      />
    </View>
  )
}

function ResetStep({
  challenge,
  onResend,
  onDone
}: {
  challenge: ChallengeResponse
  onResend: () => Promise<number>
  onDone: () => void
}) {
  const styles = useStyles()
  const [code, setCode] = useState('')
  const [codeError, setCodeError] = useState<string>()
  const countdown = useCountdown(challenge.resend_after)
  const form = useForm<ResetPasswordValues>({
    resolver: zodResolver(resetPasswordSchema),
    defaultValues: { new_password: '' }
  })
  const reset = useMutation({
    mutationFn: (values: ResetPasswordValues) =>
      authPasswordReset({
        challenge_id: challenge.challenge_id,
        code,
        ...values
      }),
    onSuccess: onDone,
    onError: () => setCode('')
  })
  const resend = useMutation({
    mutationFn: onResend,
    onSuccess: seconds => {
      countdown.restart(seconds)
      setCode('')
      setCodeError(undefined)
      reset.reset()
    },
    onError: error => countdown.restart(retryAfterSeconds(error) || 60)
  })
  const submit = form.handleSubmit(values => {
    if (reset.isPending || resend.isPending) return
    if (code.length !== 6) return setCodeError('Введите 6 цифр из письма')
    reset.mutate(values)
  })

  return (
    <View style={styles.step}>
      <Text tone='secondary'>
        Если аккаунт с этим адресом есть, код придёт на {challenge.destination}.
      </Text>
      <CodeInput
        value={code}
        onChangeText={value => {
          setCode(value)
          setCodeError(undefined)
        }}
        error={codeError}
        editable={!reset.isPending && !resend.isPending}
      />
      <FormField
        control={form.control}
        name='new_password'
        label='Новый пароль'
        secure
        autoComplete='new-password'
        textContentType='newPassword'
        editable={!reset.isPending && !resend.isPending}
        returnKeyType='done'
        onSubmitEditing={() => void submit()}
      />
      <Text
        variant='caption'
        tone='secondary'
      >
        Не короче 15 символов. Подойдёт фраза из нескольких слов.
      </Text>
      {reset.error && (
        <Notice
          tone='error'
          message={errorMessage(reset.error)}
        />
      )}
      {resend.error && (
        <Notice
          tone='error'
          message={errorMessage(resend.error, 'Не удалось отправить код')}
        />
      )}
      <Button
        title='Сохранить пароль'
        loading={reset.isPending}
        disabled={resend.isPending}
        onPress={() => void submit()}
      />
      <Button
        variant='ghost'
        title={
          countdown.remaining
            ? `Отправить снова через ${countdown.remaining} с`
            : 'Отправить код снова'
        }
        disabled={countdown.remaining > 0 || reset.isPending}
        loading={resend.isPending}
        onPress={() => resend.mutate()}
      />
    </View>
  )
}

function DoneStep() {
  const styles = useStyles()
  return (
    <View style={styles.step}>
      <Notice
        tone='success'
        message='Войдите с новым паролем. Код второго фактора всё равно понадобится — так аккаунт остаётся защищённым.'
      />
      <Button
        title='Войти'
        onPress={() => router.replace('/sign-in')}
      />
    </View>
  )
}

const useStyles = createStyles(({ spacing }) => ({
  step: { gap: spacing.md }
}))
