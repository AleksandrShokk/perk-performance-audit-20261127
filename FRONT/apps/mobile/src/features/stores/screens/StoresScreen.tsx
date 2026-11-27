import { router } from 'expo-router'
import { Plus, Store } from 'lucide-react-native'
import { View } from 'react-native'

import {
  Button,
  Card,
  EmptyState,
  ListRow,
  Notice,
  Screen,
  Skeleton,
  Text
} from '@/components/ui'

import { useWorkspace } from '@/features/workspace/providers/WorkspaceProvider'

import { createStyles } from '@/theme'

export default function StoresScreen() {
  const styles = useStyles()
  const workspace = useWorkspace()
  return (
    <Screen
      logo={false}
      bottomInset
      onRefresh={workspace.refetch}
    >
      <View style={styles.sections}>
        <Text variant='screenTitle'>Магазины</Text>
        {workspace.status === 'error' ? (
          <Notice
            tone='error'
            message='Не удалось загрузить магазины'
            actionTitle='Повторить'
            onAction={() => void workspace.refetch()}
          />
        ) : workspace.status !== 'ready' ? (
          <Skeleton height={160} />
        ) : !workspace.isAdmin ? (
          <Notice message='Управление магазинами доступно владельцу и админу.' />
        ) : (
          <>
            {workspace.connections.length ? (
              workspace.connections.map(store => (
                <Card key={store.id}>
                  <ListRow
                    icon={Store}
                    title={store.name}
                    subtitle={
                      store.marketplace === 'wildberries'
                        ? 'Wildberries · API-токен'
                        : 'Ozon'
                    }
                    onPress={() =>
                      router.push({
                        pathname: '/stores/[storeId]',
                        params: { storeId: store.id }
                      })
                    }
                  />
                </Card>
              ))
            ) : (
              <EmptyState
                icon={Store}
                title='Нет подключённых магазинов'
              />
            )}
            <Button
              title='Подключить магазин'
              icon={Plus}
              variant='secondary'
              onPress={() => router.push('/connect-store')}
            />
          </>
        )}
      </View>
    </Screen>
  )
}

const useStyles = createStyles(({ spacing }) => ({
  sections: { gap: spacing.lg, paddingTop: spacing.xxl }
}))
