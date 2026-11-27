import { router, useLocalSearchParams } from 'expo-router'
import { View } from 'react-native'

import type { StoreResponse } from '@app/api'

import {
  Button,
  Card,
  FormField,
  InfoHint,
  Notice,
  Screen,
  Skeleton,
  Text
} from '@/components/ui'

import { useAuth } from '@/features/auth/providers/AuthProvider'
import { StepUpCancelled } from '@/features/auth/stepUp/StepUpProvider'
import { useWorkspace } from '@/features/workspace/providers/WorkspaceProvider'

import { errorMessage } from '@/lib/errors'

import { OzonConnectionSettings } from '../components/OzonConnectionSettings'
import { useReplaceStoreToken } from '../hooks/useReplaceStoreToken'
import { connectionLabel, tokenExpiryLabel } from '../model/storeConnection'

import { createStyles } from '@/theme'

export default function StoreSettingsScreen() {
  const styles = useStyles()
  const { storeId } = useLocalSearchParams<{ storeId: string }>()
  const { workspace, connections, status, isAdmin, refetch } = useWorkspace()
  const store = connections.find(item => item.id === storeId)
  return (
    <Screen
      logo={false}
      bottomInset
      keyboard
    >
      <View style={styles.sections}>
        <Text variant='screenTitle'>{store?.name ?? 'Настройки магазина'}</Text>
        {status === 'error' ? (
          <Notice
            tone='error'
            message='Не удалось загрузить магазин'
            actionTitle='Повторить'
            onAction={() => void refetch()}
          />
        ) : status !== 'ready' ? (
          <Skeleton height={240} />
        ) : !isAdmin ? (
          <Notice message='Менять токен может только владелец или админ.' />
        ) : !workspace || !store ? (
          <Notice
            message='Магазин не найден'
            actionTitle='К магазинам'
            onAction={() => router.replace('/stores')}
          />
        ) : store.marketplace === 'ozon' ? (
          <OzonConnectionSettings
            key={`${workspace.id}:${store.id}`}
            workspaceId={workspace.id}
            storeId={store.id}
          />
        ) : (
          <StoreTokenForm
            key={`${workspace.id}:${store.id}`}
            workspaceId={workspace.id}
            store={store}
          />
        )}
      </View>
    </Screen>
  )
}

function StoreTokenForm({
  workspaceId,
  store
}: {
  workspaceId: string
  store: StoreResponse
}) {
  const styles = useStyles()
  const { user } = useAuth()
  const { form, connection, submit, saved, pending, error } =
    useReplaceStoreToken(workspaceId, store.id)
  const data = connection.data
  return (
    <>
      <Card style={styles.form}>
        <Text variant='bodyStrong'>Wildberries</Text>
        <View style={styles.row}>
          <Text tone='secondary'>Подключение</Text>
          <Text variant='labelStrong'>
            {connection.isPending
              ? 'Проверяем…'
              : connectionLabel(data?.status ?? store.connection_status)}
          </Text>
        </View>
        <View style={styles.row}>
          <Text tone='secondary'>Токен действует до</Text>
          <Text variant='labelStrong'>
            {tokenExpiryLabel(data?.expires_at)}
          </Text>
        </View>
      </Card>
      {connection.isError && (
        <Notice
          tone='error'
          message={errorMessage(
            connection.error,
            'Не удалось проверить подключение'
          )}
          actionTitle='Повторить'
          onAction={() => void connection.refetch()}
        />
      )}
      {!user?.strong_factor_enabled ? (
        <Notice
          message='Для замены токена привяжите телефон или подключите аутентификатор.'
          actionTitle='Привязать телефон'
          onAction={() => router.push('/phone')}
        />
      ) : (
        <View style={styles.form}>
          <View style={styles.row}>
            <Text variant='sectionTitle'>Заменить токен</Text>
            <InfoHint
              title='Новый токен Wildberries'
              message='WB → Настройки → Доступ к API. Создайте ключ только для чтения для того же продавца: Контент, Статистика, Аналитика, Финансы, Цены и скидки, Маркетплейс, Поставки. Данные магазина сохранятся.'
            />
          </View>
          <FormField
            control={form.control}
            name='token'
            label='Новый API-токен'
            secure
            autoCapitalize='none'
            autoCorrect={false}
            autoComplete='off'
            editable={!pending}
          />
          {saved && !form.formState.isDirty && (
            <Notice
              tone='success'
              message='Токен обновлён. Загрузка данных продолжится автоматически.'
            />
          )}
          {!!error && !(error instanceof StepUpCancelled) && (
            <Notice
              tone='error'
              message={errorMessage(error, 'Не удалось заменить токен')}
            />
          )}
          <Button
            title='Сохранить токен'
            loading={pending}
            onPress={submit}
          />
        </View>
      )}
    </>
  )
}

const useStyles = createStyles(({ spacing }) => ({
  sections: { gap: spacing.lg, paddingTop: spacing.xxl },
  form: { gap: spacing.md },
  row: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: spacing.sm
  }
}))
