import { useState } from 'react'
import { View } from 'react-native'

import { recoveryCode } from '@app/schemas'

import { Button, TextField } from '@/components/ui'

import { errorCode, errorMessage } from '@/lib/errors'

import { createStyles } from '@/theme'

export function RecoveryCodeForm({
  onSubmit
}: {
  onSubmit: (code: string) => Promise<void>
}) {
  const styles = useStyles()
  const [code, setCode] = useState('')
  const [error, setError] = useState<string>()
  const [pending, setPending] = useState(false)

  async function submit() {
    if (pending) return
    const parsed = recoveryCode.safeParse(code)
    if (!parsed.success) return setError(parsed.error.issues[0]?.message)
    setPending(true)
    try {
      await onSubmit(parsed.data)
    } catch (failure) {
      setError(
        errorCode(failure) === 'otp_invalid'
          ? 'Резервный код неверный или уже использован. Возьмите другой из сохранённых кодов.'
          : errorMessage(failure, 'Не удалось проверить резервный код')
      )
    } finally {
      setPending(false)
    }
  }

  return (
    <View style={styles.form}>
      <TextField
        label='Резервный код'
        placeholder='rc_…'
        hint='Одноразовый резервный код'
        value={code}
        onChangeText={value => {
          setCode(value)
          setError(undefined)
        }}
        error={error}
        autoCapitalize='none'
        autoCorrect={false}
        onSubmitEditing={submit}
      />
      <Button
        title='Подтвердить'
        loading={pending}
        onPress={submit}
      />
    </View>
  )
}

const useStyles = createStyles(({ spacing }) => ({ form: { gap: spacing.md } }))
