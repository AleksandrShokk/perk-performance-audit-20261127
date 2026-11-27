import { useInfiniteQuery } from '@tanstack/react-query'
import { View } from 'react-native'

import {
  type ProductItem,
  type ProductVariant,
  costsList,
  variantCostsList
} from '@app/api'

import { Button, Divider, Notice, Text } from '@/components/ui'

import { useAuth } from '@/features/auth/providers/AuthProvider'
import { formatFinanceMoney } from '@/features/finance/model/financeFormat'
import { useWorkspace } from '@/features/workspace/providers/WorkspaceProvider'

import { errorMessage } from '@/lib/errors'
import { formatUnits } from '@/lib/format'

import { variantId } from '../model/productIdentity'
import { sortCostHistory } from '../model/productMetrics'

import { createStyles } from '@/theme'

export function VariantDetails({
  product,
  selectedVariant,
  workspaceId,
  currency,
  onEdit
}: {
  product: ProductItem
  selectedVariant?: ProductVariant
  workspaceId: string
  currency: string
  onEdit: (variant?: ProductVariant) => void
}) {
  const styles = useStyles()
  const { can, accessKey } = useWorkspace()
  const { user } = useAuth()
  const isOzon = product.marketplace === 'ozon'
  const targetVariant = selectedVariant ?? product.variants[0]
  const history = useInfiniteQuery({
    queryKey: [
      'user',
      user?.id,
      workspaceId,
      'cost-history',
      product.store_id,
      product.id,
      isOzon ? targetVariant?.id : undefined,
      accessKey
    ],
    initialPageParam: 0,
    queryFn: async ({ pageParam, signal }) => {
      if (isOzon) {
        const rows = await variantCostsList(
          workspaceId,
          product.store_id,
          { variant_id: targetVariant!.id, limit: 100, offset: pageParam },
          { signal }
        )
        return rows.map(row => ({ ...row, nm_id: '', barcode: '' }))
      }
      return costsList(
        workspaceId,
        product.store_id,
        { nm_id: product.nm_id, limit: 100, offset: pageParam },
        { signal }
      )
    },
    getNextPageParam: (page, pages) =>
      page.length === 100 ? pages.length * 100 : undefined,
    enabled: can('profit.read') && (!isOzon || !!targetVariant?.id),
    meta: { persist: false }
  })
  const prices = sortCostHistory(history.data?.pages).filter(
    row => !row.barcode || selectedVariant?.barcodes.includes(row.barcode)
  )
  return (
    <View style={styles.content}>
      <Text
        variant='label'
        tone='secondary'
      >
        {product.vendor_code} · {product.marketplace === 'ozon' ? 'Ozon' : 'WB'}{' '}
        {product.marketplace_code || product.nm_id}
      </Text>
      {can('inventory.read') && (
        <Text variant='bodyStrong'>
          FBO: {formatUnits(selectedVariant?.stock)}
        </Text>
      )}
      <Divider />
      {(selectedVariant ? [selectedVariant] : []).map(variant => (
        <View
          key={variantId(variant)}
          style={styles.variant}
        >
          {variant.barcodes.map(code => (
            <Text
              key={code}
              selectable
              variant='caption'
              tone='secondary'
            >
              {code}
            </Text>
          ))}
          {can('profit.read') && (
            <View style={styles.row}>
              <Text
                variant='label'
                tone='secondary'
              >
                Себестоимость
              </Text>
              <Text variant='labelStrong'>
                {formatFinanceMoney(variant.unit_cost, currency)}
              </Text>
            </View>
          )}
          {variant.warehouses.map(row => (
            <View
              key={row.name}
              style={styles.row}
            >
              <Text
                variant='caption'
                tone='secondary'
              >
                {row.name}
              </Text>
              <Text variant='caption'>{formatUnits(row.quantity)}</Text>
            </View>
          ))}
          {can('inventory.read') &&
            !!(variant.to_client || variant.from_client) && (
              <Text
                variant='caption'
                tone='secondary'
              >
                К покупателю: {variant.to_client ?? '—'} · Возвращается:{' '}
                {variant.from_client ?? '—'}
              </Text>
            )}
          <Divider />
        </View>
      ))}
      {can('costs.write') && (
        <Button
          title='Добавить себестоимость'
          onPress={() => onEdit(selectedVariant)}
        />
      )}
      {can('profit.read') && (
        <>
          <Text variant='sectionTitle'>История цен</Text>
          {history.isPending && <Text tone='secondary'>Загрузка истории…</Text>}
          {history.error && (
            <Notice
              tone='error'
              message={errorMessage(history.error)}
              actionTitle='Повторить'
              onAction={() => void history.refetch()}
            />
          )}
          {!history.isPending && !history.error && !prices.length && (
            <Text tone='secondary'>Цены ещё не заданы</Text>
          )}
          {prices.map(row => (
            <View
              key={`${row.barcode}:${row.currency}:${row.effective_from}`}
              style={styles.row}
            >
              <View style={styles.name}>
                <Text variant='label'>
                  С {row.effective_from.split('-').reverse().join('.')}
                </Text>
                <Text
                  variant='caption'
                  tone='secondary'
                >
                  {isOzon
                    ? targetVariant?.size || 'Вариант товара'
                    : row.barcode || 'Все размеры'}
                </Text>
              </View>
              <Text variant='labelStrong'>
                {formatFinanceMoney(row.amount, row.currency)}
              </Text>
            </View>
          ))}
          {history.hasNextPage && (
            <Button
              title='Ещё цены'
              variant='ghost'
              loading={history.isFetchingNextPage}
              onPress={() => void history.fetchNextPage()}
            />
          )}
        </>
      )}
    </View>
  )
}
const useStyles = createStyles(({ spacing }) => ({
  content: { gap: spacing.md },
  variant: { gap: spacing.sm },
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    gap: spacing.sm
  },
  name: { flex: 1, gap: spacing.xxs }
}))
