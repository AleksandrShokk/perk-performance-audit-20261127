import { Info, X } from 'lucide-react-native'
import { useState } from 'react'
import { Modal, Pressable, ScrollView, StyleSheet, View } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'

import { Text } from './Text'
import { createStyles, useTheme } from '@/theme'

/** Короткое пояснение по нажатию; работает на Android, iOS и в браузере. */
export function InfoHint({
  title,
  message
}: {
  title: string
  message: string
}) {
  const styles = useStyles()
  const { colors, sizes, spacing } = useTheme()
  const insets = useSafeAreaInsets()
  const [visible, setVisible] = useState(false)
  const close = () => setVisible(false)
  return (
    <>
      <Pressable
        accessibilityRole='button'
        accessibilityLabel={`Что означает «${title}»`}
        accessibilityState={{ expanded: visible }}
        onPress={() => setVisible(true)}
        style={styles.trigger}
      >
        <Info
          size={sizes.icon}
          color={colors.text.secondary}
        />
      </Pressable>
      <Modal
        visible={visible}
        transparent
        animationType='fade'
        onRequestClose={close}
      >
        <View
          style={[
            styles.overlay,
            {
              paddingTop: insets.top + spacing.lg,
              paddingBottom: insets.bottom + spacing.lg
            }
          ]}
        >
          <Pressable
            style={styles.backdrop}
            onPress={close}
            accessibilityRole='button'
            accessibilityLabel='Закрыть пояснение'
          />
          <View
            style={styles.window}
            accessibilityViewIsModal
            onAccessibilityEscape={close}
          >
            <View style={styles.heading}>
              <Text
                variant='sectionTitle'
                style={styles.title}
              >
                {title}
              </Text>
              <Pressable
                style={styles.trigger}
                onPress={close}
                accessibilityRole='button'
                accessibilityLabel='Закрыть'
              >
                <X
                  size={sizes.icon}
                  color={colors.text.secondary}
                />
              </Pressable>
            </View>
            <ScrollView contentContainerStyle={styles.message}>
              <Text>{message}</Text>
            </ScrollView>
          </View>
        </View>
      </Modal>
    </>
  )
}

const useStyles = createStyles(({ colors, spacing, sizes, radius }) => ({
  trigger: {
    width: sizes.touchTarget,
    height: sizes.touchTarget,
    justifyContent: 'center',
    alignItems: 'center'
  },
  overlay: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: spacing.lg
  },
  backdrop: { ...StyleSheet.absoluteFill, backgroundColor: colors.shadow },
  window: {
    width: '100%',
    maxWidth: 360,
    maxHeight: '90%',
    backgroundColor: colors.background.card,
    borderRadius: radius.card,
    padding: spacing.lg,
    borderWidth: 1,
    borderColor: colors.border
  },
  heading: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs },
  title: { flex: 1 },
  message: { paddingTop: spacing.xs, paddingBottom: spacing.xs }
}))
