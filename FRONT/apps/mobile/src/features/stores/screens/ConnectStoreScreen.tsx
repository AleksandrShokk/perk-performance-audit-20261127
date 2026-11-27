import { initialImportMessage } from '@app/analytics/onboarding'
import { router } from 'expo-router'
import { KeyRound, Smartphone } from 'lucide-react-native'
import { useState } from 'react'
import { View } from 'react-native'

import {
  Button,
  Card,
  FormField,
  Notice,
  Screen,
  SegmentedControl,
  Text
} from '@/components/ui'

import { useAuth } from '@/features/auth/providers/AuthProvider'
import { StepUpCancelled } from '@/features/auth/stepUp/StepUpProvider'
import { useConnectStore } from '@/features/stores/hooks/useConnectStore'
import { useWorkspace } from '@/features/workspace/providers/WorkspaceProvider'

import { errorMessage } from '@/lib/errors'

import { OzonConnectForm } from '../components/OzonConnectForm'

import { createStyles, useTheme } from '@/theme'

export default function ConnectStoreScreen() {
  const styles = useStyles()
  const { colors } = useTheme()
  const { user } = useAuth()
  const { workspace, isOwner } = useWorkspace()
  const { form, submit, connected, pending, error } = useConnectStore()
  const strong = user?.strong_factor_enabled
  const [marketplace, setMarketplace] = useState<'wb' | 'ozon'>('wb')

  return (
    <Screen
      keyboard
      bottomInset
      logo={false}
    >
      <View style={styles.heading}>
        <Text variant='screenTitle'>Ваш магазин в PERK</Text>
      </View>
      {!strong ? (
        <Card style={styles.form}>
          <Smartphone
            size={28}
            color={colors.accent}
          />
          <Text variant='sectionTitle'>Сначала защитим доступ</Text>
          <Text tone='secondary'>
            Подтвердите телефон или подключите аутентификатор.
          </Text>
          <Button
            title='Привязать телефон'
            onPress={() => router.push('/phone')}
          />
        </Card>
      ) : !isOwner ? (
        <Notice message='Подключить магазин может только владелец кабинета.' />
      ) : (
        <View style={styles.form}>
          <SegmentedControl
            options={[
              { value: 'wb', label: 'Wildberries' },
              { value: 'ozon', label: 'Ozon' }
            ]}
            value={marketplace}
            onChange={setMarketplace}
          />
          {marketplace === 'ozon' ? (
            <OzonConnectForm />
          ) : (
            <>
              <Card style={styles.instructions}>
                <KeyRound
                  color={colors.accent}
                  size={22}
                />
                <Text variant='bodyStrong'>Ключ API Wildberries</Text>
                <Text
                  variant='label'
                  tone='secondary'
                >
                  WB → Настройки → Доступ к API. Ключ только для чтения:
                  Контент, Статистика, Аналитика, Финансы, Цены и скидки,
                  Маркетплейс, Поставки.
                </Text>
              </Card>
              <Notice message={initialImportMessage} />
              {!connected && (
                <>
                  <FormField
                    control={form.control}
                    name='name'
                    label='Название магазина'
                    placeholder='Например, Мотосклад'
                  />
                  <FormField
                    control={form.control}
                    name='token'
                    label='Ключ API'
                    secure
                    autoCapitalize='none'
                    autoCorrect={false}
                    autoComplete='off'
                  />
                </>
              )}
              {connected && (
                <Notice
                  title='Магазин подключён'
                  message='Не удалось запустить загрузку. Повторите попытку.'
                />
              )}
              {!!error && !(error instanceof StepUpCancelled) && (
                <Notice
                  tone='error'
                  message={errorMessage(error, 'Не удалось подключить магазин')}
                />
              )}
              <Button
                title={
                  connected ? 'Запустить загрузку' : 'Подключить Wildberries'
                }
                loading={pending}
                disabled={!workspace}
                onPress={submit}
              />
            </>
          )}
        </View>
      )}
    </Screen>
  )
}

const useStyles = createStyles(({ spacing }) => ({
  heading: {
    gap: spacing.sm,
    marginTop: spacing.huge,
    marginBottom: spacing.xl
  },
  form: { gap: spacing.md },
  instructions: { gap: spacing.sm }
}))
