import { router } from 'expo-router'
import { View } from 'react-native'

import { Button, Card, FormField, Notice, Text } from '@/components/ui'

import { useAuth } from '@/features/auth/providers/AuthProvider'
import { StepUpCancelled } from '@/features/auth/stepUp/StepUpProvider'

import { errorMessage } from '@/lib/errors'

import { useOzonConnection } from '../hooks/useOzonConnection'
import { connectionLabel, tokenExpiryLabel } from '../model/storeConnection'

import { OzonCatalogStatus } from './OzonCatalogStatus'
import { createStyles } from '@/theme'

export function OzonConnectionSettings({
  workspaceId,
  storeId
}: {
  workspaceId: string
  storeId: string
}) {
  const styles = useStyles()
  const { user } = useAuth()
  const {
    form,
    connection,
    check,
    submit,
    saved,
    checked,
    pending,
    checking,
    saving,
    error
  } = useOzonConnection(workspaceId, storeId)
  const data = connection.data
  return (
    <>
      <Card style={styles.form}>
        <Text variant='sectionTitle'>Ozon</Text>
        <View style={styles.row}>
          <Text tone='secondary'>Client ID</Text>
          <Text
            variant='labelStrong'
            selectable
          >
            {data?.client_id ?? '—'}
          </Text>
        </View>
        <View style={styles.row}>
          <Text tone='secondary'>Подключение</Text>
          <Text variant='labelStrong'>
            {connection.isPending
              ? 'Проверяем…'
              : connectionLabel(data?.status ?? '')}
          </Text>
        </View>
        <View style={styles.row}>
          <Text tone='secondary'>Ключ действует до</Text>
          <Text variant='labelStrong'>
            {tokenExpiryLabel(data?.expires_at)}
          </Text>
        </View>
      </Card>
      <OzonCatalogStatus
        workspaceId={workspaceId}
        storeId={storeId}
      />
      {connection.isError && (
        <Notice
          tone='error'
          message={errorMessage(
            connection.error,
            'Не удалось загрузить подключение'
          )}
          actionTitle='Повторить'
          onAction={() => void connection.refetch()}
        />
      )}
      {!user?.strong_factor_enabled ? (
        <Notice
          message='Для управления ключом подтвердите телефон или подключите аутентификатор.'
          actionTitle='Привязать телефон'
          onAction={() => router.push('/phone')}
        />
      ) : (
        <Card style={styles.form}>
          <Button
            title='Проверить подключение'
            variant='secondary'
            loading={checking}
            disabled={pending || !data}
            onPress={check}
          />
          {checked && !error && (
            <Notice
              tone='success'
              message='Подключение работает'
            />
          )}
          <Text variant='bodyStrong'>Заменить API Key</Text>
          <FormField
            control={form.control}
            name='api_key'
            label='Новый Seller API Key'
            secure
            autoCapitalize='none'
            autoCorrect={false}
            autoComplete='off'
            editable={!pending}
          />
          {!!error && !(error instanceof StepUpCancelled) && (
            <Notice
              tone='error'
              message={errorMessage(error, 'Не удалось обновить подключение')}
            />
          )}
          {saved && (
            <Notice
              tone='success'
              message='Ключ обновлён'
            />
          )}
          <Button
            title='Сохранить ключ'
            loading={saving}
            disabled={checking || !data?.client_id}
            onPress={submit}
          />
        </Card>
      )}
    </>
  )
}
const useStyles = createStyles(({ spacing }) => ({
  form: { gap: spacing.md },
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: spacing.sm
  }
}))
