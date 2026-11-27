import { useLocalSearchParams } from 'expo-router'

import { authRegisterResend, authRegisterVerify } from '@app/api'

import { AuthLayout } from '@/features/auth/components/AuthLayout'
import { CodeStep } from '@/features/auth/components/CodeStep'
import { useAuth } from '@/features/auth/providers/AuthProvider'
import { getAuthClient } from '@/features/auth/session/client'

type Params = { challengeId: string; destination: string; resendAfter?: string }

export default function VerifyEmailScreen() {
  const { challengeId, destination, resendAfter } =
    useLocalSearchParams<Params>()
  const { startSession } = useAuth()

  return (
    <AuthLayout
      title='Подтвердите почту'
      subtitle='Аккаунт появится сразу после ввода кода из письма.'
    >
      <CodeStep
        destination={`на ${destination}`}
        resendAfter={Number(resendAfter) || 60}
        onSubmit={async code => {
          const response = await authRegisterVerify({
            challenge_id: challengeId,
            code,
            client: getAuthClient()
          })
          await startSession(response)
        }}
        onResend={async () =>
          (await authRegisterResend({ challenge_id: challengeId })).resend_after
        }
      />
    </AuthLayout>
  )
}
