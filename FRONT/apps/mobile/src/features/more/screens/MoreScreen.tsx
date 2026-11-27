import { router } from 'expo-router'
import {
  Boxes,
  ShieldCheck,
  Store,
  Truck,
  User,
  Users
} from 'lucide-react-native'

import { Card, Divider, ListRow, Screen, Text } from '@/components/ui'

import { useAuth } from '@/features/auth/providers/AuthProvider'
import { useWorkspace } from '@/features/workspace/providers/WorkspaceProvider'

import { createStyles } from '@/theme'

export default function MoreScreen() {
  const styles = useStyles()
  const { user } = useAuth()
  const { isOwner, can } = useWorkspace()
  return (
    <Screen contentStyle={styles.content}>
      <Text variant='screenTitle'>Ещё</Text>
      {can('inventory.read') && (
        <Card>
          <ListRow
            icon={Boxes}
            title='Остатки'
            onPress={() =>
              router.push({
                pathname: '/reports/[topic]',
                params: { topic: 'stock' }
              })
            }
          />
          <Divider />
          <ListRow
            icon={Truck}
            title='Поставки'
            onPress={() => router.push('/supplies')}
          />
        </Card>
      )}
      <Card>
        <ListRow
          icon={User}
          title='Профиль'
          subtitle={user?.email}
          onPress={() => router.push('/profile')}
        />
        {!user?.phone && (
          <>
            <Divider />
            <ListRow
              icon={ShieldCheck}
              title='Защита аккаунта'
              subtitle='Привяжите телефон'
              onPress={() => router.push('/phone')}
            />
          </>
        )}
        {isOwner && (
          <>
            <Divider />
            <ListRow
              icon={Users}
              title='Команда'
              subtitle='Сотрудники и права'
              onPress={() => router.push('/team')}
            />
            <Divider />
            <ListRow
              icon={Store}
              title='Магазины'
              subtitle='Подключения и API-токены'
              onPress={() => router.push('/stores')}
            />
          </>
        )}
      </Card>
    </Screen>
  )
}

const useStyles = createStyles(({ spacing }) => ({
  content: { gap: spacing.lg }
}))
