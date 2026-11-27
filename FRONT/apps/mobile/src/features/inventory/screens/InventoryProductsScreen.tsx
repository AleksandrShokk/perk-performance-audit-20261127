import { Package } from 'lucide-react-native'
import { useState } from 'react'
import { FlatList, Pressable, View } from 'react-native'

import type { InventoryPosition } from '@app/api'

import {
  BottomSheet,
  Button,
  EmptyState,
  Notice,
  Screen,
  Skeleton,
  Text,
  TextField
} from '@/components/ui'

import { ProductDisplaySelect } from '@/features/products/components/ProductDisplaySelect'
import { productId } from '@/features/products/model/productIdentity'
import { StoreSwitcher } from '@/features/workspace/components/StoreSwitcher'
import { useWorkspace } from '@/features/workspace/providers/WorkspaceProvider'

import { useModalController } from '@/hooks/useModalController'

import { errorMessage } from '@/lib/errors'

import {
  PageHeading,
  ProfileButton
} from '../../../components/navigation/PageHeader'
import {
  InventoryDetails,
  InventoryProduct
} from '../components/InventoryProduct'
import { useInventory } from '../hooks/useInventory'

import { createStyles } from '@/theme'

export default function InventoryProductsScreen() {
  const styles = useStyles()
  const { workspace, store, accessKey, status, can, refetch } = useWorkspace()
  if (status === 'loading' || status === 'idle')
    return (
      <Screen
        logo={false}
        bottomInset
        contentStyle={styles.loading}
      >
        <Skeleton height={200} />
      </Screen>
    )
  if (status === 'error')
    return (
      <Screen
        logo={false}
        bottomInset
        contentStyle={styles.loading}
      >
        <Notice
          tone='error'
          message='Не удалось загрузить магазины'
          actionTitle='Повторить'
          onAction={() => void refetch()}
        />
      </Screen>
    )
  if (!can('inventory.read'))
    return (
      <Screen
        logo={false}
        bottomInset
        contentStyle={styles.loading}
      >
        <Notice message='Нет доступа к остаткам.' />
      </Screen>
    )
  return (
    <InventoryList
      key={`${workspace?.id}:${store?.id ?? 'all'}:${accessKey}`}
    />
  )
}

function InventoryList() {
  const styles = useStyles()
  const { stores, allStores } = useWorkspace()
  const [search, setSearch] = useState('')
  const [inStock, setInStock] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [selected, setSelected] = useState<InventoryPosition | null>(null)
  const modal = useModalController()
  const query = useInventory(search, inStock)
  const pages = query.data?.pages ?? []
  const data = pages[0]
  const items = pages.flatMap(page => page.items)
  // Use a fresh row when background polling updates the open product.
  const product =
    selected &&
    (items.find(
      item =>
        item.product.store_id === selected.product.store_id &&
        productId(item.product) === productId(selected.product)
    ) ??
      selected)
  async function close() {
    await modal.dismiss()
    setSelected(null)
  }
  return (
    <Screen
      headerCenter={stores.length ? <StoreSwitcher compact /> : undefined}
      headerRight={<ProfileButton />}
      bottomInset
      bottomSpacing={0}
      scroll={false}
      contentStyle={styles.body}
    >
      <FlatList
        data={items}
        keyExtractor={item =>
          `${item.product.store_id}:${productId(item.product)}`
        }
        contentContainerStyle={styles.list}
        keyboardShouldPersistTaps='handled'
        showsVerticalScrollIndicator={false}
        refreshing={refreshing}
        onRefresh={() => {
          setRefreshing(true)
          void query.refetch().finally(() => setRefreshing(false))
        }}
        ListHeaderComponent={
          <View style={styles.header}>
            <PageHeading title='По товарам' />
            <TextField
              label='Поиск товаров'
              placeholder='Название, артикул или штрихкод'
              value={search}
              onChangeText={setSearch}
              maxLength={100}
              autoCapitalize='none'
              returnKeyType='search'
              clearButtonMode='while-editing'
            />
            <View style={styles.row}>
              <Pressable
                accessibilityRole='checkbox'
                accessibilityState={{ checked: inStock }}
                style={[styles.filter, inStock && styles.active]}
                onPress={() => setInStock(value => !value)}
              >
                <Text variant='labelStrong'>В наличии</Text>
              </Pressable>
              <ProductDisplaySelect />
            </View>
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
        renderItem={({ item }) => (
          <InventoryProduct
            position={item}
            allStores={allStores}
            onPress={() => {
              setSelected(item)
              void modal.open()
            }}
          />
        )}
        ListEmptyComponent={
          query.isPending && stores.length ? (
            <Skeleton height={200} />
          ) : !query.error ? (
            <EmptyState
              icon={Package}
              title={
                !stores.length
                  ? 'Подключите магазин'
                  : search || inStock
                    ? 'Товары не найдены'
                    : 'Каталог ещё не загружен'
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
        visible={modal.visible}
        onDismiss={modal.onDismiss}
        title='Остатки товара'
        onClose={() => void close()}
      >
        {product && (
          <InventoryDetails
            position={product}
            currency={data?.currency}
            canCost={data?.can_cost}
          />
        )}
      </BottomSheet>
    </Screen>
  )
}

const useStyles = createStyles(({ colors, spacing, radius, sizes }) => ({
  loading: { paddingTop: spacing.huge },
  body: { flex: 1, minHeight: 0 },
  list: { gap: spacing.md, paddingBottom: spacing.lg },
  header: { gap: spacing.md },
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: spacing.sm,
    flexWrap: 'wrap'
  },
  filter: {
    minHeight: sizes.touchTarget,
    paddingHorizontal: spacing.md,
    borderRadius: radius.chip,
    justifyContent: 'center',
    backgroundColor: colors.background.card
  },
  active: { backgroundColor: colors.accentSoft }
}))
