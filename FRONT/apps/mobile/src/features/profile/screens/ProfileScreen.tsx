import { router } from 'expo-router'
import { LogOut, ShieldCheck } from 'lucide-react-native'
import { Alert, Platform, View } from 'react-native'

import {
  Avatar,
  Button,
  Card,
  ListRow,
  Pill,
  Screen,
  Text
} from '@/components/ui'

import { useAuth } from '@/features/auth/providers/AuthProvider'
import { ROLE_LABELS } from '@/features/team/model/permissions'
import { useWorkspace } from '@/features/workspace/providers/WorkspaceProvider'

import { createStyles } from '@/theme'

export default function ProfileScreen() {
  const styles = useStyles()
  const { user, signOut } = useAuth()
  const { workspace, workspaces, selectWorkspace, isAdmin } = useWorkspace()
  return (
    <Screen
      bottomInset
      logo={false}
    >
      <View style={styles.header}>
        <Avatar
          name={user?.email ?? ''}
          size={64}
        />
        <Text variant='sectionTitle'>{user?.email}</Text>
        <Text tone='secondary'>{workspace?.name}</Text>
        <Pill label={ROLE_LABELS[workspace?.role ?? 'viewer'] ?? 'Сотрудник'} />
      </View>
      <Card>
        <ListRow
          icon={ShieldCheck}
          title={user?.phone ? 'Сменить номер' : 'Привязать телефон'}
          subtitle={user?.phone ?? 'Нужен для входа и ключа магазина'}
          onPress={() => router.push('/phone')}
        />
        <ListRow
          title='Сменить пароль'
          onPress={() => router.push('/change-password')}
        />
      </Card>
      {isAdmin && (
        <Card>
          <ListRow
            title='Команда'
            subtitle='Сотрудники и права доступа'
            onPress={() => router.push('/team')}
          />
        </Card>
      )}
      {workspaces.length > 1 && (
        <Card>
          {workspaces.map(item => (
            <ListRow
              key={item.id}
              title={item.name}
              subtitle={
                item.id === workspace?.id
                  ? 'Текущий кабинет'
                  : ROLE_LABELS[item.role]
              }
              onPress={
                item.id === workspace?.id
                  ? undefined
                  : () => void selectWorkspace(item.id)
              }
            />
          ))}
        </Card>
      )}
      <Button
        title='Выйти из аккаунта'
        variant='ghost'
        icon={LogOut}
        onPress={() => {
          if (Platform.OS === 'web') {
            void signOut()
            return
          }
          Alert.alert(
            'Выйти из PERK?',
            'Последние отчёты будут удалены с этого устройства.',
            [
              { text: 'Отмена', style: 'cancel' },
              {
                text: 'Выйти',
                style: 'destructive',
                onPress: () => void signOut()
              }
            ]
          )
        }}
      />
    </Screen>
  )
}

const useStyles = createStyles(({ spacing }) => ({
  header: {
    alignItems: 'center',
    gap: spacing.sm,
    marginTop: spacing.huge,
    marginBottom: spacing.xxl
  }
}))
