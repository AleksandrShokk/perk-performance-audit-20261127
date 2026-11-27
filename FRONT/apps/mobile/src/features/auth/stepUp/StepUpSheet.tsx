import { useMutation } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Modal, View } from 'react-native'

import { authStepUpSend, authStepUpVerify } from '@app/api'

import { Button, Notice, Screen, Text } from '@/components/ui'

import { errorMessage } from '@/lib/errors'

import { CodeStep } from '../components/CodeStep'
import { RecoveryCodeForm } from '../components/RecoveryCodeForm'
import { describeDestination } from '../model/channels'
import { useAuth } from '../providers/AuthProvider'

import { createStyles } from '@/theme'

type StepUpSheetProps = {
  strong: boolean
  visible: boolean
  onDismiss: () => void
  onConfirmed: () => Promise<void>
  onCancel: () => void
}

export function StepUpSheet({
  strong,
  visible,
  onDismiss,
  onConfirmed,
  onCancel
}: StepUpSheetProps) {
  const styles = useStyles()
  const { user } = useAuth()
  const [recovery, setRecovery] = useState(false)
  const authenticator = !!user?.totp_enabled
  // Без канала сервер выберет основной: Telegram/SMS, а без телефона — почту.
  const send = useMutation({ mutationFn: () => authStepUpSend({}) })
  const challenge = send.data
  const { mutate: sendCode } = send

  // Код отправляется один раз при открытии окна.
  useEffect(() => {
    if (!authenticator) sendCode()
  }, [sendCode, authenticator])

  async function verify(code: string) {
    await authStepUpVerify({ code })
    await onConfirmed()
  }

  return (
    <Modal
      visible={visible}
      onDismiss={onDismiss}
      animationType='slide'
      presentationStyle='pageSheet'
      onRequestClose={onCancel}
    >
      <Screen
        keyboard
        bottomInset
      >
        <View style={styles.header}>
          <Text variant='screenTitle'>Подтвердите действие</Text>
          <Text tone='secondary'>
            {authenticator
              ? 'Введите код из приложения-аутентификатора.'
              : strong
                ? 'Это изменение защищено: введите код из Telegram или SMS.'
                : 'Введите код, чтобы продолжить.'}
          </Text>
        </View>

        {recovery ? (
          <RecoveryCodeForm onSubmit={verify} />
        ) : send.isError ? (
          <Notice
            tone='error'
            message={errorMessage(send.error, 'Не удалось отправить код')}
            actionTitle='Повторить'
            onAction={() => send.mutate()}
          />
        ) : (
          <CodeStep
            key={challenge?.challenge_id ?? 'pending'}
            destination={challenge && describeDestination(challenge)}
            resendAfter={challenge?.resend_after ?? 60}
            onSubmit={verify}
            onResend={
              authenticator
                ? undefined
                : async () => (await send.mutateAsync()).resend_after
            }
          />
        )}

        {user?.strong_factor_enabled && (
          <Button
            title={
              recovery ? 'Ввести обычный код' : 'Использовать резервный код'
            }
            variant='ghost'
            onPress={() => setRecovery(value => !value)}
          />
        )}

        <Button
          variant='ghost'
          title='Отмена'
          onPress={onCancel}
        />
      </Screen>
    </Modal>
  )
}

const useStyles = createStyles(({ spacing }) => ({
  header: { gap: spacing.xs, marginTop: spacing.xl, marginBottom: spacing.xl }
}))
