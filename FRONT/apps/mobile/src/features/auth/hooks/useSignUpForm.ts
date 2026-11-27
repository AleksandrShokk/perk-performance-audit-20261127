import { zodResolver } from '@hookform/resolvers/zod'
import { router } from 'expo-router'
import { useForm } from 'react-hook-form'

import { type SignUpValues, signUpSchema } from '@app/schemas'

import { useAuthRegister } from '@app/api'

import { getAuthClient } from '@/features/auth/session/client'
import { usePendingInvite } from '@/features/team/providers/PendingInviteProvider'

/** Регистрация: аккаунт создаётся только после кода из письма (экран verify-email). */
export function useSignUpForm() {
  const register = useAuthRegister()
  const invite = usePendingInvite()
  const form = useForm<SignUpValues>({
    resolver: zodResolver(signUpSchema),
    defaultValues: {
      email: invite.details?.email ?? '',
      password: '',
      workspace_name: invite.code
        ? (invite.details?.workspace_name ?? 'Команда')
        : ''
    }
  })

  const submit = form.handleSubmit(async values => {
    const challenge = await register.mutateAsync({
      data: {
        ...values,
        invite_code: invite.code ?? undefined,
        client: getAuthClient()
      }
    })
    router.push({
      pathname: '/verify-email',
      params: {
        challengeId: challenge.challenge_id,
        destination: challenge.destination,
        resendAfter: String(challenge.resend_after)
      }
    })
  })

  return {
    control: form.control,
    submit: () => void submit().catch(() => {}),
    isPending: register.isPending || form.formState.isSubmitting,
    error: register.error
  }
}
