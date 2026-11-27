import { router } from 'expo-router'
import { Check, ChevronDown, Plus } from 'lucide-react-native'
import { useState } from 'react'
import { Modal, Pressable, View } from 'react-native'

import { Avatar, Button, Divider, ListRow, Screen, Text } from '@/components/ui'

import { marketplaceName } from '../model/marketplaceName'
import { useWorkspace } from '../providers/WorkspaceProvider'

import { createStyles, useTheme } from '@/theme'

export function StoreSwitcher({ compact = false }: { compact?: boolean }) {
  const styles = useStyles()
  const { colors } = useTheme()
  const { store, stores, allStores, isOwner, selectStore } = useWorkspace()
  const [visible, setVisible] = useState(false)

  return (
    <>
      <Pressable
        style={[styles.current, compact && styles.compact]}
        onPress={() => setVisible(true)}
        accessibilityRole='button'
        accessibilityLabel='Выбрать магазин'
      >
        {!compact && (
          <Avatar
            name={allStores ? 'Все магазины' : (store?.name ?? 'М')}
            size={28}
          />
        )}
        <View style={compact ? styles.compactName : styles.name}>
          <Text
            variant={compact ? 'bodyStrong' : 'label'}
            tone={compact ? 'primary' : 'secondary'}
            style={compact && styles.centeredText}
            numberOfLines={1}
          >
            {allStores
              ? compact
                ? 'Все магазины'
                : 'Все магазины · Весь бизнес'
              : compact
                ? (store?.name ?? 'Выбрать магазин')
                : `${store?.name ?? 'Выбрать магазин'} · ${marketplaceName(store?.marketplace)}`}
          </Text>
          {compact && (
            <Text
              variant='caption'
              tone='secondary'
              style={styles.centeredText}
              numberOfLines={1}
            >
              {allStores ? 'Весь бизнес' : marketplaceName(store?.marketplace)}
            </Text>
          )}
        </View>
        <ChevronDown
          size={16}
          color={colors.text.secondary}
        />
      </Pressable>
      <Modal
        visible={visible}
        animationType='slide'
        presentationStyle='pageSheet'
        onRequestClose={() => setVisible(false)}
      >
        <Screen bottomInset>
          <View style={styles.heading}>
            <Text variant='screenTitle'>Магазины</Text>
            <Button
              title='Готово'
              variant='ghost'
              onPress={() => setVisible(false)}
            />
          </View>
          {stores.length > 1 && (
            <>
              <ListRow
                title='Все магазины'
                subtitle='Статистика по всему бизнесу'
                trailing={
                  allStores ? (
                    <Check
                      size={20}
                      color={colors.accent}
                    />
                  ) : undefined
                }
                onPress={() => {
                  selectStore('all')
                  setVisible(false)
                }}
              />
              <Divider />
            </>
          )}
          {stores.map(item => (
            <View key={item.id}>
              <ListRow
                title={item.name}
                subtitle={
                  item.connection_status === 'connected'
                    ? `${marketplaceName(item.marketplace)} · подключён`
                    : 'Проверьте подключение'
                }
                trailing={
                  item.id === store?.id ? (
                    <Check
                      size={20}
                      color={colors.accent}
                    />
                  ) : undefined
                }
                onPress={() => {
                  selectStore(item.id)
                  setVisible(false)
                }}
              />
              <Divider />
            </View>
          ))}
          {isOwner && (
            <Button
              title='Подключить магазин'
              variant='secondary'
              icon={Plus}
              onPress={() => {
                setVisible(false)
                router.push('/connect-store')
              }}
            />
          )}
        </Screen>
      </Modal>
    </>
  )
}

const useStyles = createStyles(({ spacing, sizes }) => ({
  current: {
    minHeight: sizes.touchTarget,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs
  },
  name: { flex: 1, minWidth: 0 },
  compact: { justifyContent: 'center' },
  compactName: { minWidth: 0, flexShrink: 1 },
  centeredText: { textAlign: 'center' },
  heading: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginVertical: spacing.lg
  }
}))
