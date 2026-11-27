import { router } from 'expo-router'
import { Store } from 'lucide-react-native'
import { Pressable, View } from 'react-native'

import {
  Avatar,
  Card,
  EmptyState,
  Notice,
  Screen,
  Skeleton,
  Text
} from '@/components/ui'

import { useAuth } from '@/features/auth/providers/AuthProvider'
import { StoreSwitcher } from '@/features/workspace/components/StoreSwitcher'
import { useWorkspace } from '@/features/workspace/providers/WorkspaceProvider'

import { errorMessage } from '@/lib/errors'

import { HomeSalesCard } from '../home/components/HomeSalesCard'
import {
  AnalyticsShortcuts,
  CriticalCards,
  FinanceSummary,
  type OverviewTopic,
  SearchPlaceholder,
  StockSummary
} from '../home/components/OverviewSections'
import { useHomeFilters } from '../home/hooks/useHomeFilters'
import { useHomeOverview } from '../home/hooks/useHomeOverview'

import { createStyles } from '@/theme'

export default function OverviewScreen() {
  const styles = useStyles()
  const { user } = useAuth()
  const workspace = useWorkspace()
  const { filters, setFilters, ready } = useHomeFilters()
  const overview = useHomeOverview(filters, ready)
  const empty = workspace.status === 'ready' && workspace.stores.length === 0
  const open = (topic: OverviewTopic) =>
    router.push({
      pathname: '/reports/[topic]',
      params: {
        topic,
        ...(['orders', 'buyouts', 'funnel'].includes(topic)
          ? overview.range
          : {})
      }
    })
  const openFinance = () => router.push('/(tabs)/finance')

  return (
    <Screen
      stickyHeader
      headerCenter={
        workspace.stores.length ? (
          <StoreSwitcher compact />
        ) : (
          <Text
            variant='bodyStrong'
            numberOfLines={1}
          >
            Мой магазин
          </Text>
        )
      }
      headerRight={
        <Pressable
          accessibilityRole='button'
          accessibilityLabel='Профиль'
          onPress={() => router.push('/profile')}
        >
          <Avatar name={user?.email ?? ''} />
        </Pressable>
      }
      onRefresh={async () => {
        await overview.refresh()
        if (workspace.status === 'error') await workspace.refetch()
      }}
    >
      <View style={styles.sections}>
        <SearchPlaceholder />
        {workspace.status === 'error' ? (
          <Notice
            tone='error'
            message='Не удалось загрузить магазины'
            actionTitle='Повторить'
            onAction={() => void workspace.refetch()}
          />
        ) : workspace.status === 'loading' ? (
          <Skeleton height={120} />
        ) : empty ? (
          <Card>
            <EmptyState
              icon={Store}
              title={
                workspace.isAdmin
                  ? 'Ваш бизнес — в цифрах'
                  : 'Нет доступных магазинов'
              }
              description={
                workspace.isAdmin
                  ? 'Подключите магазин: соберём заказы, выкупы, расходы и остатки.'
                  : 'Попросите администратора открыть доступ к магазину.'
              }
              actionTitle={
                workspace.isOwner ? 'Подключить Wildberries' : undefined
              }
              onAction={
                workspace.isOwner
                  ? () => router.push('/connect-store')
                  : undefined
              }
            />
          </Card>
        ) : (
          <>
            {overview.error && (
              <Notice
                tone='error'
                message={errorMessage(overview.error)}
                actionTitle='Повторить'
                onAction={() => void overview.refresh()}
              />
            )}
            {(workspace.supports('supplies') ||
              workspace.supports('finance')) && (
              <CriticalCards
                overview={overview}
                onSupplies={() => router.push('/supplies')}
                onFinance={openFinance}
              />
            )}
            {workspace.supports('analytics') &&
              workspace.can('analytics.read') && (
                <HomeSalesCard
                  overview={overview}
                  filters={filters}
                  onChange={setFilters}
                />
              )}
            {workspace.supports('analytics') ? (
              <AnalyticsShortcuts onOpen={open} />
            ) : (
              <Notice
                message={
                  workspace.allStores
                    ? 'Общие финансы и аналитика появятся после подключения остальных данных Ozon.'
                    : 'Ozon: товары и остатки подключены. Финансы и аналитика — следующий этап.'
                }
              />
            )}
            {workspace.supports('finance') && workspace.can('finance.read') && (
              <FinanceSummary
                overview={overview}
                onPress={openFinance}
              />
            )}
            {workspace.can('inventory.read') && (
              <StockSummary
                overview={overview}
                onPress={() => open('stock')}
              />
            )}
          </>
        )}
      </View>
    </Screen>
  )
}

const useStyles = createStyles(({ spacing }) => ({
  sections: { gap: spacing.lg }
}))
