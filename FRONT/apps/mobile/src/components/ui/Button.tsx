import type { LucideIcon } from 'lucide-react-native'
import {
  ActivityIndicator,
  Pressable,
  type PressableProps,
  View
} from 'react-native'

import { Text } from './Text'
import { createStyles, useTheme } from '@/theme'

type ButtonVariant = 'primary' | 'secondary' | 'ghost'

export type ButtonProps = Omit<PressableProps, 'children' | 'style'> & {
  title: string
  variant?: ButtonVariant
  icon?: LucideIcon
  loading?: boolean
  /** Растянуть на всю ширину (по умолчанию для основной кнопки). */
  block?: boolean
}

export function Button({
  title,
  variant = 'primary',
  icon: Icon,
  loading = false,
  block = variant === 'primary',
  disabled,
  ...props
}: ButtonProps) {
  const styles = useStyles()
  const { colors } = useTheme()
  const inactive = disabled || loading
  const tint = variant === 'primary' ? colors.onAccent : colors.accent

  return (
    <Pressable
      accessibilityRole='button'
      accessibilityState={{ disabled: inactive, busy: loading }}
      disabled={inactive}
      {...props}
      style={({ pressed }) => [
        styles.base,
        styles[variant],
        block && styles.block,
        pressed && styles.pressed,
        disabled && !loading && styles.disabled
      ]}
    >
      {/* Текст остаётся в разметке во время загрузки, чтобы кнопка не меняла ширину. */}
      <View style={[styles.content, loading && styles.hidden]}>
        {Icon && (
          <Icon
            size={18}
            color={tint}
          />
        )}
        <Text
          variant='bodyStrong'
          style={{ color: tint }}
          numberOfLines={1}
        >
          {title}
        </Text>
      </View>
      {loading && (
        <ActivityIndicator
          color={tint}
          style={styles.spinner}
        />
      )}
    </Pressable>
  )
}

const useStyles = createStyles(({ colors, radius, sizes, spacing }) => ({
  base: {
    minHeight: sizes.button,
    borderRadius: radius.control,
    paddingHorizontal: spacing.lg,
    alignItems: 'center',
    justifyContent: 'center'
  },
  primary: { backgroundColor: colors.accent },
  secondary: { backgroundColor: colors.accentSoft },
  ghost: { backgroundColor: 'transparent', paddingHorizontal: spacing.sm },
  block: { alignSelf: 'stretch' },
  pressed: { opacity: 0.75, transform: [{ scale: 0.985 }] },
  disabled: { opacity: 0.45 },
  content: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs },
  hidden: { opacity: 0 },
  spinner: { position: 'absolute' }
}))
