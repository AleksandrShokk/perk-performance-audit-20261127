import { Check, ChevronDown } from 'lucide-react-native'
import { Pressable, View } from 'react-native'

import type { StoreResponse } from '@app/api'

import { BottomSheet, ListRow, Text } from '@/components/ui'

import { marketplaceName } from '@/features/workspace/model/marketplaceName'

import { useModalController } from '@/hooks/useModalController'

import { createStyles, useTheme } from '@/theme'

export function SupplyStoreFilter({
  stores,
  storeId,
  onChange,
  quantity
}: {
  stores: StoreResponse[]
  storeId?: string
  onChange: (storeId: string | undefined) => void
  quantity?: string
}) {
  const styles = useStyles()
  const { colors } = useTheme()
  const modal = useModalController()
  if (stores.length < 2) return null
  const selected = stores.find(store => store.id === storeId)
  const options = [
    { id: undefined, name: 'Все кабинеты', marketplace: undefined },
    ...stores
  ]
  async function select(id: string | undefined) {
    await modal.dismiss()
    onChange(id)
  }
  return (
    <>
      <View style={styles.row}>
        <Pressable
          style={styles.button}
          onPress={() => void modal.open()}
          accessibilityRole='button'
          accessibilityLabel={`Фильтр по кабинету: ${selected?.name ?? 'Все кабинеты'}`}
          accessibilityState={{ expanded: modal.visible }}
        >
          <Text
            variant='bodyStrong'
            numberOfLines={1}
            style={styles.name}
          >
            {selected?.name ?? 'Все кабинеты'}
          </Text>
          <ChevronDown
            size={18}
            color={colors.text.secondary}
          />
        </Pressable>
        {selected && quantity && (
          <Text
            variant='labelStrong'
            tabular
          >
            {quantity}
          </Text>
        )}
      </View>
      <BottomSheet
        title='Кабинеты'
        visible={modal.visible}
        onDismiss={modal.onDismiss}
        onClose={() => void modal.dismiss()}
      >
        {options.map(option => (
          <ListRow
            key={option.id ?? 'all'}
            title={option.name}
            subtitle={
              option.marketplace
                ? marketplaceName(option.marketplace)
                : undefined
            }
            trailing={
              option.id === storeId ? (
                <Check
                  size={20}
                  color={colors.accent}
                />
              ) : undefined
            }
            onPress={() => void select(option.id)}
          />
        ))}
      </BottomSheet>
    </>
  )
}

const useStyles = createStyles(({ colors, radius, spacing, sizes }) => ({
  row: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  button: {
    flex: 1,
    minWidth: 0,
    minHeight: sizes.touchTarget,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    paddingHorizontal: spacing.md,
    borderRadius: radius.control,
    backgroundColor: colors.background.card
  },
  name: { flex: 1, minWidth: 0 }
}))
