import { router } from 'expo-router'
import { Package, Truck } from 'lucide-react-native'
import { useState } from 'react'
import { FlatList, Switch, View } from 'react-native'

import type { ReplenishmentItem, SupplyCard } from '@app/api'

import {
  BottomSheet,
  Button,
  Card,
  EmptyState,
  InfoHint,
  Notice,
  Screen,
  SegmentedControl,
  Skeleton,
  Text
} from '@/components/ui'

import { StoreSwitcher } from '@/features/workspace/components/StoreSwitcher'
import { UpcomingReport } from '@/features/workspace/components/UpcomingReport'
import { useWorkspace } from '@/features/workspace/providers/WorkspaceProvider'

import { useModalController } from '@/hooks/useModalController'

import { errorMessage } from '@/lib/errors'
import { formatUnits } from '@/lib/format'

import {
  PageHeading,
  ProfileButton
} from '../../../components/navigation/PageHeader'
import { ReplenishmentTotals } from '../components/ReplenishmentTotals'
import {
  ImportedSupplyDetails,
  ReplenishmentDetails
} from '../components/SupplyDetails'
import { ReplenishmentRow, SupplyRow } from '../components/SupplyRows'
import { SupplyStoreFilter } from '../components/SupplyStoreFilter'
import {
  useReplenishment,
  useReplenishmentList,
  useSupplies,
  useSupplyStoreFilter
} from '../hooks/useSupplies'

import { createStyles } from '@/theme'

const tabs = [
  { value: 'recommendations', label: 'Рекомендации' },
  { value: 'imported', label: 'Оформленные' }
] as const

export default function SuppliesScreen() {
  const styles = useStyles()
  const workspace = useWorkspace()
  const [tab, setTab] = useState<'recommendations' | 'imported'>(
    'recommendations'
  )
  const currentTab = workspace.supports('supply_history')
    ? tab
    : 'recommendations'
  if (workspace.stores.length && !workspace.supports('supplies'))
    return <UpcomingReport />
  return (
    <Screen
      scroll={false}
      bottomInset
      bottomSpacing={0}
      contentStyle={styles.body}
      headerCenter={
        workspace.stores.length ? <StoreSwitcher compact /> : undefined
      }
      headerRight={<ProfileButton />}
    >
      <View style={styles.heading}>
        <PageHeading title='Поставки'>
          <InfoHint
            title='Поставки'
            message={
              'Рекомендации показывают, сколько товара довезти на FBO для запаса на 30 дней после поступления. На подготовку, доставку и приёмку заложено 7 дней. WB и Ozon: все фактические заказы товара за 28 календарных дней. Оформленные партии учитываются по товарам: плановая дата плюс срок доставки и приёмки. Партии без актуальной даты не уменьшают потребность. Учитывается заданная в PERK кратность коробов.\n\n«Оформленные» — поставки из кабинетов Wildberries и Ozon. Нажмите карточку, чтобы посмотреть детали.'
            }
          />
        </PageHeading>
        {workspace.can('inventory.read') &&
          workspace.supports('supply_history') && (
            <SegmentedControl
              options={tabs}
              value={tab}
              onChange={setTab}
            />
          )}
      </View>
      {workspace.status === 'loading' || workspace.status === 'idle' ? (
        <Skeleton height={240} />
      ) : workspace.status === 'error' ? (
        <Notice
          tone='error'
          message='Не удалось загрузить магазины'
          actionTitle='Повторить'
          onAction={() => void workspace.refetch()}
        />
      ) : !workspace.can('inventory.read') ? (
        <Notice message='Нет доступа к поставкам.' />
      ) : !workspace.stores.length ? (
        <EmptyState
          icon={Truck}
          title='Подключите магазин'
        />
      ) : (
        <View
          style={styles.body}
          key={`${workspace.workspace?.id}:${workspace.store?.id ?? 'all'}:${workspace.accessKey}:${tab}`}
        >
          {currentTab === 'recommendations' ? (
            <Recommendations />
          ) : (
            <PlacedSupplies />
          )}
        </View>
      )}
    </Screen>
  )
}

function Recommendations() {
  const styles = useStyles()
  const { allStores } = useWorkspace()
  const filter = useSupplyStoreFilter()
  const [includeFbs, setIncludeFbs] = useState(false)
  const query = useReplenishmentList(filter.storeId, includeFbs)
  const summary = useReplenishment(includeFbs)
  const data = query.data?.pages[0]
  const totals = summary.data ?? (!filter.storeId ? data : undefined)
  const error = query.error ?? summary.error
  const refresh = () => Promise.all([query.refetch(), summary.refetch()])
  const items = query.data?.pages.flatMap(page => page.items) ?? []
  const [selected, setSelected] = useState<ReplenishmentItem | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const modal = useModalController()
  const item =
    selected &&
    (items.find(
      row =>
        row.store_id === selected.store_id &&
        (row.id || row.nm_id) === (selected.id || selected.nm_id)
    ) ??
      selected)
  return (
    <>
      <FlatList
        data={items}
        keyExtractor={row => row.id || `${row.store_id}:${row.nm_id}`}
        contentContainerStyle={styles.list}
        showsVerticalScrollIndicator={false}
        refreshing={refreshing}
        onRefresh={() => {
          setRefreshing(true)
          void refresh().finally(() => setRefreshing(false))
        }}
        ListHeaderComponent={
          <View style={styles.heading}>
            <ReplenishmentTotals
              data={totals}
              allStores={allStores}
            />
            <View
              style={{
                flexDirection: 'row',
                alignItems: 'center',
                justifyContent: 'space-between'
              }}
            >
              <Text>Вычитать остатки FBS</Text>
              <Switch
                accessibilityLabel='Вычитать остатки FBS из потребности'
                value={includeFbs}
                onValueChange={setIncludeFbs}
              />
            </View>
            <SupplyStoreFilter
              stores={filter.stores}
              storeId={filter.storeId}
              onChange={filter.setStoreId}
              quantity={formatUnits(data?.recommended_units)}
            />
            {error && (
              <Notice
                tone='error'
                message={errorMessage(error)}
                actionTitle='Повторить'
                onAction={() => void refresh()}
              />
            )}
          </View>
        }
        renderItem={({ item: row }) => (
          <Card>
            <ReplenishmentRow
              item={row}
              allStores={allStores && !filter.storeId}
              onPress={() => {
                setSelected(row)
                void modal.open()
              }}
            />
          </Card>
        )}
        ListEmptyComponent={
          query.isPending ? (
            <Skeleton height={180} />
          ) : !query.error ? (
            <EmptyState
              icon={Package}
              title={
                data?.recommended_units == null
                  ? 'Расчёт ещё не готов'
                  : 'Пополнение не требуется'
              }
            />
          ) : undefined
        }
        ListFooterComponent={
          query.hasNextPage ? (
            <Button
              title='Показать ещё'
              variant='ghost'
              loading={query.isFetchingNextPage}
              onPress={() => void query.fetchNextPage()}
            />
          ) : undefined
        }
      />
      <BottomSheet
        title='Рекомендация к поставке'
        visible={modal.visible}
        onDismiss={modal.onDismiss}
        onClose={() => void modal.dismiss()}
      >
        {item && <ReplenishmentDetails item={item} />}
      </BottomSheet>
    </>
  )
}

function PlacedSupplies() {
  const styles = useStyles()
  const { allStores, isAdmin, store } = useWorkspace()
  const filter = useSupplyStoreFilter('supply_history')
  const query = useSupplies(filter.storeId)
  const data = query.data?.pages[0]
  const items = query.data?.pages.flatMap(page => page.items) ?? []
  const [selected, setSelected] = useState<SupplyCard | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const modal = useModalController()
  const plan =
    selected &&
    (items.find(
      row =>
        row.store_id === selected.store_id &&
        row.external_id === selected.external_id
    ) ??
      selected)
  return (
    <>
      <FlatList
        data={items}
        keyExtractor={row => `${row.store_id}:${row.external_id}`}
        contentContainerStyle={styles.list}
        showsVerticalScrollIndicator={false}
        refreshing={refreshing}
        onRefresh={() => {
          setRefreshing(true)
          void query.refetch().finally(() => setRefreshing(false))
        }}
        ListHeaderComponent={
          <View style={styles.heading}>
            <SupplyStoreFilter
              stores={filter.stores}
              storeId={filter.storeId}
              onChange={filter.setStoreId}
            />
            {data?.missing_access && (
              <Notice
                message='Проверьте права на поставки в ключе кабинета.'
                actionTitle={isAdmin ? 'Настроить ключ' : undefined}
                onAction={
                  isAdmin
                    ? () =>
                        store
                          ? router.push({
                              pathname: '/stores/[storeId]',
                              params: { storeId: store.id }
                            })
                          : router.push('/stores')
                    : undefined
                }
              />
            )}
            {query.error && (
              <Notice
                tone='error'
                message={errorMessage(query.error)}
                actionTitle='Повторить'
                onAction={() => void query.refetch()}
              />
            )}
          </View>
        }
        renderItem={({ item: row }) => (
          <Card>
            <SupplyRow
              plan={row}
              allStores={allStores && !filter.storeId}
              onPress={() => {
                setSelected(row)
                void modal.open()
              }}
            />
          </Card>
        )}
        ListEmptyComponent={
          query.isPending ? (
            <Skeleton height={180} />
          ) : !query.error && !data?.missing_access ? (
            <EmptyState
              icon={Truck}
              title={
                data?.loading
                  ? 'Загружаем поставки'
                  : data?.incomplete
                    ? 'Поставки ещё не загружены'
                    : 'Оформленных поставок пока нет'
              }
            />
          ) : undefined
        }
        ListFooterComponent={
          query.hasNextPage ? (
            <Button
              title='Показать ещё'
              variant='ghost'
              loading={query.isFetchingNextPage}
              onPress={() => void query.fetchNextPage()}
            />
          ) : undefined
        }
      />
      <BottomSheet
        title='Оформленная поставка'
        visible={modal.visible}
        onDismiss={modal.onDismiss}
        onClose={() => void modal.dismiss()}
      >
        {plan && <ImportedSupplyDetails plan={plan} />}
      </BottomSheet>
    </>
  )
}

const useStyles = createStyles(({ spacing }) => ({
  body: { flex: 1, minHeight: 0 },
  heading: { gap: spacing.md, paddingBottom: spacing.md },
  list: { gap: spacing.md, paddingBottom: spacing.lg }
}))
