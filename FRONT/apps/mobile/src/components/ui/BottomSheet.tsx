import { X } from 'lucide-react-native'
import type { ReactNode } from 'react'
import {
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  View
} from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'

import { Text } from './Text'
import { createStyles, useTheme } from '@/theme'

export function BottomSheet({
  title,
  children,
  onClose,
  visible = true,
  onDismiss
}: {
  title: string
  children: ReactNode
  onClose: () => void
  visible?: boolean
  onDismiss?: () => void
}) {
  const styles = useStyles()
  const { colors, spacing } = useTheme()
  const insets = useSafeAreaInsets()
  return (
    <Modal
      visible={visible}
      onDismiss={onDismiss}
      transparent
      animationType='slide'
      onRequestClose={onClose}
    >
      <KeyboardAvoidingView
        style={styles.overlay}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        <Pressable
          style={styles.backdrop}
          onPress={onClose}
          accessibilityLabel='Закрыть'
          accessibilityRole='button'
        />
        <View
          accessibilityViewIsModal
          style={[
            styles.sheet,
            { paddingBottom: Math.max(insets.bottom, spacing.lg) }
          ]}
        >
          <View style={styles.heading}>
            <Text
              variant='sectionTitle'
              style={styles.title}
            >
              {title}
            </Text>
            <Pressable
              onPress={onClose}
              style={styles.close}
              accessibilityRole='button'
              accessibilityLabel='Закрыть'
            >
              <X
                size={22}
                color={colors.text.secondary}
              />
            </Pressable>
          </View>
          <ScrollView
            showsVerticalScrollIndicator={false}
            keyboardShouldPersistTaps='handled'
            contentContainerStyle={styles.content}
          >
            {children}
          </ScrollView>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  )
}

const useStyles = createStyles(({ colors, radius, spacing }) => ({
  overlay: { flex: 1, justifyContent: 'flex-end' },
  backdrop: { ...StyleSheet.absoluteFill, backgroundColor: colors.shadow },
  sheet: {
    maxHeight: '90%',
    backgroundColor: colors.background.card,
    borderTopLeftRadius: radius.card,
    borderTopRightRadius: radius.card,
    padding: spacing.lg
  },
  heading: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginBottom: spacing.md
  },
  title: { flex: 1 },
  close: { padding: spacing.sm },
  content: { gap: spacing.md }
}))
