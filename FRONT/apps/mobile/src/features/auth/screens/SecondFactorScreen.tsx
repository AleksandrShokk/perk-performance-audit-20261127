import { useState } from 'react'
import { View } from 'react-native'

import { Button, Notice } from '@/components/ui'

import { AuthLayout } from '@/features/auth/components/AuthLayout'
import { CodeStep } from '@/features/auth/components/CodeStep'
import { RecoveryCodeForm } from '@/features/auth/components/RecoveryCodeForm'
import { useSecondFactor } from '@/features/auth/hooks/useSecondFactor'
import {
  CHANNEL_LABELS,
  codeDeliveryMessage,
  describeDestination
} from '@/features/auth/model/channels'

import { errorMessage } from '@/lib/errors'

import { createStyles } from '@/theme'

export default function SecondFactorScreen() {
  const styles = useStyles()
  const factor = useSecondFactor()
  const [recoveryMode, setRecoveryMode] = useState(false)
  const sending = factor.isSending
  const [sendError, setSendError] = useState<unknown>(null)

  const sendCode = async (channel?: Parameters<typeof factor.send>[0]) => {
    setSendError(null)
    try {
      await factor.send(channel)
      setRecoveryMode(false)
    } catch (error) {
      setSendError(error)
    }
  }

  const alternatives = (
    <View style={styles.alternatives}>
      {factor.otherChannels.map(channel => (
        <Button
          key={channel}
          variant='ghost'
          title={`Получить код: ${CHANNEL_LABELS[channel]}`}
          onPress={() => sendCode(channel)}
          disabled={sending || factor.retryAfter > 0}
        />
      ))}
      {recoveryMode && (
        <Button
          variant='ghost'
          title='Вернуться к коду'
          onPress={() => setRecoveryMode(false)}
        />
      )}
      {factor.canUseRecovery && !recoveryMode && (
        <Button
          variant='ghost'
          title='Ввести резервный код'
          onPress={() => setRecoveryMode(true)}
        />
      )}
      <Button
        variant='ghost'
        title='Войти в другой аккаунт'
        onPress={factor.signOut}
      />
    </View>
  )

  return (
    <AuthLayout
      title='Подтвердите вход'
      subtitle={
        factor.usesAuthenticator
          ? 'Введите 6 цифр из приложения-аутентификатора.'
          : 'Это защищает доступ к выручке и ключам магазина.'
      }
    >
      {!!(factor.deliveryError || sendError) && (
        <Notice
          tone='error'
          message={
            sendError
              ? errorMessage(sendError, 'Не удалось отправить код')
              : codeDeliveryMessage(factor.deliveryError)
          }
        />
      )}

      {recoveryMode ? (
        <RecoveryCodeForm onSubmit={factor.verify} />
      ) : factor.needsSending ? (
        <Button
          title={
            factor.retryAfter
              ? `Отправить код через ${factor.retryAfter} с`
              : 'Отправить код'
          }
          disabled={factor.retryAfter > 0}
          loading={sending}
          onPress={() => sendCode()}
        />
      ) : (
        <CodeStep
          key={factor.challenge?.challenge_id ?? 'authenticator'}
          destination={
            factor.challenge ? describeDestination(factor.challenge) : undefined
          }
          resendAfter={factor.retryAfter}
          onSubmit={factor.verify}
          onResend={
            factor.challenge
              ? () => factor.send(factor.challenge?.channel)
              : undefined
          }
        />
      )}

      {alternatives}
    </AuthLayout>
  )
}

const useStyles = createStyles(({ spacing }) => ({
  alternatives: {
    alignItems: 'center',
    gap: spacing.xxs,
    marginTop: spacing.xs
  }
}))
