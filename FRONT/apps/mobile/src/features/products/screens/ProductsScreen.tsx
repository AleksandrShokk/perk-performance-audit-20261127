import { router } from 'expo-router'
import { Check, FileUp, Package } from 'lucide-react-native'
import { useState } from 'react'
import { FlatList, Pressable, View } from 'react-native'

import type { ProductItem, ProductModel, ProductVariant } from '@app/api'

import {
  Avatar,
  BottomSheet,
  Button,
  EmptyState,
  Notice,
  Screen,
  Skeleton,
  Text,
  TextField
} from '@/components/ui'

import { useAuth } from '@/features/auth/providers/AuthProvider'
import { CostImport } from '@/features/finance/components/CostImport'
import { StoreSwitcher } from '@/features/workspace/components/StoreSwitcher'
import { useWorkspace } from '@/features/workspace/providers/WorkspaceProvider'

import { useModalController } from '@/hooks/useModalController'

import { errorMessage } from '@/lib/errors'
import { formatNumber, plural } from '@/lib/format'

import { CostEditor } from '../components/CostEditor'
import { GroupingForm } from '../components/GroupingForm'
import { ProductCard } from '../components/ProductCard'
import { ProductDetails } from '../components/ProductDetails'
import { ProductDisplaySelect } from '../components/ProductDisplaySelect'
import { useProducts, useRefreshProducts } from '../hooks/useProducts'
import { productFeed } from '../model/productFeed'
import { productId, variantId } from '../model/productIdentity'
import { useProductDisplay } from '../providers/ProductDisplayProvider'

import { createStyles, useTheme } from '@/theme'

type Sheet =
  | {
      model: ProductModel
      product?: ProductItem
      variant?: ProductVariant
      mode: 'details' | 'price' | 'group'
    }
  | 'import'

export default function ProductsScreen() {
  const { workspace, store, can, accessKey, status, refetch } = useWorkspace()
  if (status === 'loading' || status === 'idle')
    return (
      <Screen>
        <Skeleton height={180} />
      </Screen>
    )
  if (status === 'error')
    return (
      <Screen>
        <Notice
          tone='error'
          message='Не удалось загрузить магазины'
          actionTitle='Повторить'
          onAction={() => void refetch()}
        />
      </Screen>
    )
  if (!can('inventory.read') && !can('profit.read'))
    return (
      <Screen>
        <Notice message='Нет доступа к товарам.' />
      </Screen>
    )
  // Remount the page when its cabinet or grants change, including any open form.
  return <Catalog key={`${workspace?.id}:${store?.id ?? 'all'}:${accessKey}`} />
}

function Catalog() {
  const styles = useStyles()
  const { colors, sizes } = useTheme()
  const { showAllVariants, setShowAllVariants } = useProductDisplay()
  const { user } = useAuth()
  const { workspace, store, stores, allStores, can } = useWorkspace()
  const [search, setSearch] = useState('')
  const [inStock, setInStock] = useState(false)
  const [missingCost, setMissingCost] = useState(false)
  const [saved, setSaved] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [sheet, setSheet] = useState<Sheet | null>(null)
  const modal = useModalController()
  const query = useProducts(search, inStock, missingCost)
  const refresh = useRefreshProducts()
  const pages = query.data?.pages ?? []
  const data = pages[0]
  const items = productFeed(
    pages.flatMap(page => page.items),
    showAllVariants
  )
  const total = showAllVariants ? data?.total_products : data?.total
  function open(value: Sheet) {
    setSaved(false)
    setSheet(value)
    void modal.open()
  }
  async function close() {
    await modal.dismiss()
    setSheet(null)
  }
  async function onSaved() {
    await close()
    setSaved(true)
    void refresh()
  }
  const filters = [
    ...(can('inventory.read')
      ? [
          {
            label: 'В наличии',
            value: inStock,
            toggle: () => setInStock(value => !value)
          }
        ]
      : []),
    ...(can('profit.read')
      ? [
          {
            label: 'Без себестоимости',
            value: missingCost,
            toggle: () => setMissingCost(value => !value)
          }
        ]
      : [])
  ]
  return (
    <Screen
      scroll={false}
      contentStyle={styles.body}
      headerCenter={stores.length ? <StoreSwitcher compact /> : undefined}
      headerRight={
        <Pressable
          accessibilityRole='button'
          accessibilityLabel='Профиль'
          onPress={() => router.push('/profile')}
        >
          <Avatar name={user?.email ?? ''} />
        </Pressable>
      }
    >
      <FlatList
        data={items}
        keyExtractor={item => item.card.id}
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
            <View style={styles.row}>
              <Text variant='screenTitle'>Товары</Text>
              {can('costs.write') && store?.marketplace === 'wildberries' && (
                <Button
                  title='Импорт'
                  icon={FileUp}
                  variant='ghost'
                  onPress={() => open('import')}
                />
              )}
            </View>
            <TextField
              label='Поиск товаров'
              maxLength={100}
              placeholder='Название, артикул или штрихкод'
              value={search}
              onChangeText={setSearch}
              autoCapitalize='none'
              returnKeyType='search'
              clearButtonMode='while-editing'
            />
            <View style={styles.filters}>
              {filters.map(filter => (
                <Pressable
                  key={filter.label}
                  accessibilityRole='checkbox'
                  accessibilityState={{ checked: filter.value }}
                  onPress={filter.toggle}
                  style={[styles.filter, filter.value && styles.selected]}
                >
                  <Text variant='labelStrong'>{filter.label}</Text>
                </Pressable>
              ))}
            </View>
            <Pressable
              accessibilityRole='checkbox'
              accessibilityLabel='Показывать все варианты в ленте'
              accessibilityState={{ checked: showAllVariants }}
              onPress={() => setShowAllVariants(!showAllVariants)}
              style={styles.displayOption}
            >
              <View
                style={[styles.checkbox, showAllVariants && styles.checked]}
              >
                {showAllVariants && (
                  <Check
                    size={sizes.icon}
                    color={colors.onAccent}
                  />
                )}
              </View>
              <Text
                variant='label'
                style={styles.optionLabel}
              >
                Показывать все варианты в ленте
              </Text>
            </Pressable>
            <View style={styles.row}>
              <Text
                variant='caption'
                tone='secondary'
              >
                {data
                  ? `${formatNumber(total!)} ${plural(total!, showAllVariants ? ['артикул', 'артикула', 'артикулов'] : ['карточка', 'карточки', 'карточек'])} · ${formatNumber(data.total_variants)} ${plural(data.total_variants, ['вариант', 'варианта', 'вариантов'])}`
                  : 'Каталог'}
              </Text>
              <ProductDisplaySelect />
            </View>
            {saved && (
              <Notice
                tone='success'
                message='Изменения сохранены.'
              />
            )}
            {data?.error_code && (
              <Notice
                tone='error'
                message='Не удалось обновить каталог Ozon. Загрузка повторится автоматически.'
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
        renderItem={({ item }) => (
          <ProductCard
            product={item.card}
            currency={data?.currency ?? 'RUB'}
            allStores={allStores}
            canCost={can('profit.read')}
            canStock={can('inventory.read')}
            onPress={() =>
              open({
                model: item.group,
                product: item.selectedProduct,
                mode: 'details'
              })
            }
          />
        )}
        ListEmptyComponent={
          query.isPending && stores.length ? (
            <Skeleton height={180} />
          ) : !query.error ? (
            <EmptyState
              icon={Package}
              title={
                !stores.length
                  ? 'Подключите магазин'
                  : search || inStock || missingCost
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
        title={
          sheet === 'import'
            ? 'Импорт себестоимости'
            : sheet?.mode === 'price'
              ? 'Новая цена'
              : sheet?.mode === 'group'
                ? 'Объединение товаров'
                : 'Карточка товара'
        }
        onClose={() => void close()}
      >
        {sheet === 'import' && workspace && store ? (
          <CostImport
            workspaceId={workspace.id}
            storeId={store.id}
            onSaved={onSaved}
          />
        ) : sheet && sheet !== 'import' && workspace ? (
          sheet.mode === 'price' && sheet.product ? (
            <CostEditor
              workspaceId={workspace.id}
              product={sheet.product}
              variant={sheet.variant}
              currency={data?.currency ?? 'RUB'}
              onSaved={onSaved}
              onCancel={() => setSheet({ ...sheet, mode: 'details' })}
            />
          ) : sheet.mode === 'group' ? (
            <GroupingForm
              workspaceId={workspace.id}
              model={sheet.model}
              article={sheet.product?.nm_id}
              onSaved={onSaved}
              onCancel={() => setSheet({ ...sheet, mode: 'details' })}
            />
          ) : (
            <ProductDetails
              workspaceId={workspace.id}
              model={sheet.model}
              currency={data?.currency ?? 'RUB'}
              initialArticle={
                sheet.product ? productId(sheet.product) : undefined
              }
              initialSize={sheet.variant ? variantId(sheet.variant) : undefined}
              onEdit={(product, variant) =>
                setSheet({ ...sheet, product, variant, mode: 'price' })
              }
              onGroup={(product, variant) =>
                setSheet({ ...sheet, product, variant, mode: 'group' })
              }
            />
          )
        ) : null}
      </BottomSheet>
    </Screen>
  )
}
const useStyles = createStyles(({ colors, spacing, radius, sizes }) => ({
  body: { flex: 1, minHeight: 0 },
  list: { gap: spacing.md, paddingBottom: spacing.xxl + spacing.huge },
  header: { gap: spacing.sm },
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: spacing.sm
  },
  displayOption: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    minHeight: sizes.touchTarget
  },
  optionLabel: { flex: 1 },
  checkbox: {
    width: sizes.iconLarge,
    height: sizes.iconLarge,
    borderRadius: spacing.xxs,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: 'center',
    justifyContent: 'center'
  },
  checked: { backgroundColor: colors.accent, borderColor: colors.accent },
  filters: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs },
  filter: {
    minHeight: sizes.touchTarget,
    paddingHorizontal: spacing.sm,
    justifyContent: 'center',
    borderRadius: radius.chip,
    backgroundColor: colors.background.card
  },
  selected: { backgroundColor: colors.accentSoft }
}))
