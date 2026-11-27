import { Check, ChevronDown } from 'lucide-react-native'
import { useState } from 'react'
import { Modal, Pressable, StyleSheet, View } from 'react-native'

import { Card, ListRow, Text } from '@/components/ui'

import { PRODUCT_LABEL_OPTIONS } from '../model/productLabel'
import { useProductDisplay } from '../providers/ProductDisplayProvider'

import { createStyles, useTheme } from '@/theme'

export function ProductDisplaySelect() {
  const styles = useStyles()
  const { colors } = useTheme()
  const { mode, setMode } = useProductDisplay()
  const [open, setOpen] = useState(false)
  return (
    <>
      <Pressable
        style={styles.button}
        onPress={() => setOpen(true)}
        accessibilityRole='button'
        accessibilityLabel='Отображение товаров'
        accessibilityState={{ expanded: open }}
      >
        <Text
          variant='caption'
          tone='secondary'
        >
          {PRODUCT_LABEL_OPTIONS.find(option => option.value === mode)?.label}
        </Text>
        <ChevronDown
          size={16}
          color={colors.text.secondary}
        />
      </Pressable>
      <Modal
        visible={open}
        transparent
        animationType='fade'
        onRequestClose={() => setOpen(false)}
      >
        <View style={styles.overlay}>
          <Pressable
            style={styles.backdrop}
            onPress={() => setOpen(false)}
            accessibilityRole='button'
            accessibilityLabel='Закрыть'
          />
          <Card style={styles.window}>
            <Text variant='sectionTitle'>Отображение товаров</Text>
            {PRODUCT_LABEL_OPTIONS.map(option => (
              <ListRow
                key={option.value}
                title={option.label}
                trailing={
                  mode === option.value ? (
                    <Check
                      size={20}
                      color={colors.accent}
                    />
                  ) : undefined
                }
                onPress={() => {
                  setMode(option.value)
                  setOpen(false)
                }}
              />
            ))}
          </Card>
        </View>
      </Modal>
    </>
  )
}

const useStyles = createStyles(({ colors, spacing, sizes }) => ({
  button: {
    minHeight: sizes.touchTarget,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xxs
  },
  overlay: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: spacing.lg
  },
  backdrop: { ...StyleSheet.absoluteFill, backgroundColor: colors.shadow },
  window: { width: '100%', maxWidth: 360, gap: spacing.xs }
}))
