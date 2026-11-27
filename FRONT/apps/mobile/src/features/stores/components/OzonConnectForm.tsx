import { initialImportMessage } from '@app/analytics/onboarding'

import { Button, Card, FormField, Notice, Text } from '@/components/ui'

import { StepUpCancelled } from '@/features/auth/stepUp/StepUpProvider'

import { errorMessage } from '@/lib/errors'

import { useConnectOzon } from '../hooks/useConnectOzon'

import { createStyles } from '@/theme'

export function OzonConnectForm() {
  const styles = useStyles()
  const { form, submit, pending, error } = useConnectOzon()
  return (
    <Card style={styles.form}>
      <Text variant='sectionTitle'>Подключение Ozon</Text>
      <Text
        variant='caption'
        tone='secondary'
      >
        Ozon Seller → Настройки → API-интеграции. Выберите права только для
        чтения.
      </Text>
      <FormField
        control={form.control}
        name='name'
        label='Название магазина'
        placeholder='Например, Мотосклад'
        editable={!pending}
      />
      <FormField
        control={form.control}
        name='client_id'
        label='Client ID'
        keyboardType='number-pad'
        autoCapitalize='none'
        autoCorrect={false}
        editable={!pending}
      />
      <FormField
        control={form.control}
        name='api_key'
        label='Seller API Key'
        secure
        autoCapitalize='none'
        autoCorrect={false}
        autoComplete='off'
        editable={!pending}
      />
      {!!error && !(error instanceof StepUpCancelled) && (
        <Notice
          tone='error'
          message={errorMessage(error, 'Не удалось подключить Ozon')}
        />
      )}
      <Notice message={initialImportMessage} />
      <Button
        title='Подключить Ozon'
        loading={pending}
        onPress={submit}
      />
    </Card>
  )
}
const useStyles = createStyles(({ spacing }) => ({ form: { gap: spacing.md } }))
