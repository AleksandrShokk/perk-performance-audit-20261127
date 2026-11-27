import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm, useWatch } from 'react-hook-form'

import { type SignInValues, signInSchema } from '@app/schemas'

import { useAuthLogin } from '@app/api'

import { getAuthClient } from '@/features/auth/session/client'
import { usePendingInvite } from '@/features/team/providers/PendingInviteProvider'

import { useAuth } from '../providers/AuthProvider'

/** Вход паролем. Код второго фактора сервер отправит сам; дальше — экран кода. */
export function useSignInForm() {
  const { startSession } = useAuth()
  const login = useAuthLogin()
  const invite = usePendingInvite()
  const [sessionError, setSessionError] = useState<unknown>(null)
  const form = useForm<SignInValues>({
    resolver: zodResolver(signInSchema),
    defaultValues: { email: invite.details?.email ?? '', password: '' }
  })
  const email = useWatch({ control: form.control, name: 'email' })

  const submit = form.handleSubmit(async values => {
    setSessionError(null)
    try {
      const response = await login.mutateAsync({
        data: { ...values, client: getAuthClient() }
      })
      await startSession(response)
    } catch (error) {
      setSessionError(error)
      throw error
    }
  })

  return {
    control: form.control,
    email,
    submit: () => void submit().catch(() => {}),
    isPending: login.isPending || form.formState.isSubmitting,
    error: sessionError ?? login.error
  }
}
