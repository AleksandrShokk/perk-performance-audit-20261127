import { type ReactNode, useRef, useState } from 'react'
import { View } from 'react-native'

import { Button, CodeInput, Text } from '@/components/ui'

import { useCountdown } from '@/hooks/useCountdown'

import { errorMessage, retryAfterSeconds } from '@/lib/errors'

import { createStyles } from '@/theme'

type CodeStepProps = {
  /** Куда отправлен код: «на s***@mail.ru», «в Telegram на +7 *** 45-67». */
  destination?: string
  /** Проверка кода. Ошибка показывается под ячейками, код очищается. */
  onSubmit: (code: string) => Promise<unknown>
  /** Повторная отправка; возвращает, через сколько секунд можно повторить снова. */
  onResend?: () => Promise<number>
  resendAfter?: number
  /** Дополнительные действия под формой: другой способ, резервный код. */
  footer?: ReactNode
}

export function CodeStep({
  destination,
  onSubmit,
  onResend,
  resendAfter = 60,
  footer
}: CodeStepProps) {
  const styles = useStyles()
  const [code, setCode] = useState('')
  const [error, setError] = useState<string>()
  const [submitting, setSubmitting] = useState(false)
  const [resending, setResending] = useState(false)
  const verifying = useRef(false)
  const countdown = useCountdown(resendAfter)

  async function submit(value = code) {
    if (value.length !== 6 || verifying.current) return
    verifying.current = true
    setSubmitting(true)
    setError(undefined)
    try {
      await onSubmit(value)
    } catch (failure) {
      setError(errorMessage(failure, 'Не удалось проверить код'))
      setCode('')
    } finally {
      verifying.current = false
      setSubmitting(false)
    }
  }

  async function resend() {
    if (!onResend || submitting || resending) return
    setResending(true)
    setError(undefined)
    try {
      countdown.restart(await onResend())
      setCode('')
    } catch (failure) {
      countdown.restart(retryAfterSeconds(failure) || 60)
      setError(errorMessage(failure, 'Не удалось отправить код'))
    } finally {
      setResending(false)
    }
  }

  return (
    <View style={styles.step}>
      {destination && <Text tone='secondary'>Код отправлен {destination}</Text>}
      <CodeInput
        value={code}
        onChangeText={value => {
          setCode(value)
          setError(undefined)
        }}
        onComplete={submit}
        editable={!submitting && !resending}
        error={error}
      />
      <Button
        title='Подтвердить'
        loading={submitting}
        disabled={code.length !== 6 || resending}
        onPress={() => submit()}
      />
      {onResend && (
        <Button
          variant='ghost'
          title={
            countdown.remaining
              ? `Отправить снова через ${countdown.remaining} с`
              : 'Отправить код снова'
          }
          disabled={countdown.remaining > 0 || submitting}
          loading={resending}
          onPress={resend}
        />
      )}
      {footer}
    </View>
  )
}

const useStyles = createStyles(({ spacing }) => ({
  step: { gap: spacing.md }
}))
