import { View } from 'react-native'

import { Button, FormField, Notice, Screen, Text } from '@/components/ui'

import { errorMessage } from '@/lib/errors'

import { useChangePassword } from '../hooks/useChangePassword'
import { StepUpCancelled } from '../stepUp/StepUpProvider'

import { createStyles } from '@/theme'

export default function ChangePasswordScreen() {
  const styles = useStyles()
  const form = useChangePassword()
  return (
    <Screen
      keyboard
      bottomInset
      logo={false}
    >
      <View style={styles.content}>
        <Text variant='screenTitle'>Смена пароля</Text>
        <FormField
          control={form.control}
          name='password'
          label='Текущий пароль'
          secure
          autoComplete='current-password'
          textContentType='password'
          editable={!form.pending}
        />
        <FormField
          control={form.control}
          name='new_password'
          label='Новый пароль'
          secure
          autoComplete='new-password'
          textContentType='newPassword'
          editable={!form.pending}
          returnKeyType='done'
          onSubmitEditing={() => void form.submit()}
        />
        <Text
          variant='caption'
          tone='secondary'
        >
          Не короче 15 символов. После смены войдите заново на всех устройствах.
        </Text>
        {form.error && !(form.error instanceof StepUpCancelled) && (
          <Notice
            tone='error'
            message={errorMessage(form.error)}
          />
        )}
        <Button
          title='Сохранить пароль'
          loading={form.pending}
          onPress={() => void form.submit()}
        />
      </View>
    </Screen>
  )
}

const useStyles = createStyles(({ spacing }) => ({
  content: { marginTop: spacing.huge, gap: spacing.lg }
}))
