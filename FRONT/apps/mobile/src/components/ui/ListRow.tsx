import { ChevronRight, type LucideIcon } from 'lucide-react-native'
import type { ReactNode } from 'react'
import { Pressable, View } from 'react-native'

import { Text } from './Text'
import { createStyles, useTheme } from '@/theme'

type ListRowProps = {
  title: string
  subtitle?: string
  icon?: LucideIcon
  /** Значение справа: сумма, статус. */
  trailing?: ReactNode
  onPress?: () => void
  destructive?: boolean
}

/** Строка списка: значок, название, подпись и значение справа. */
export function ListRow({
  title,
  subtitle,
  icon: Icon,
  trailing,
  onPress,
  destructive
}: ListRowProps) {
  const styles = useStyles()
  const { colors } = useTheme()
  const tint = destructive ? colors.error : colors.text.primary

  const content = (
    <>
      {Icon && (
        <View style={styles.icon}>
          <Icon
            size={20}
            color={destructive ? colors.error : colors.text.secondary}
          />
        </View>
      )}
      <View style={styles.text}>
        <Text
          variant='bodyStrong'
          style={{ color: tint }}
          numberOfLines={2}
        >
          {title}
        </Text>
        {subtitle && (
          <Text
            variant='label'
            tone='secondary'
            numberOfLines={1}
          >
            {subtitle}
          </Text>
        )}
      </View>
      {trailing}
      {onPress && !trailing && (
        <ChevronRight
          size={18}
          color={colors.text.secondary}
        />
      )}
    </>
  )

  if (!onPress) return <View style={styles.row}>{content}</View>

  return (
    <Pressable
      accessibilityRole='button'
      onPress={onPress}
      style={({ pressed }) => [styles.row, pressed && styles.pressed]}
    >
      {content}
    </Pressable>
  )
}

const useStyles = createStyles(({ colors, radius, spacing }) => ({
  row: {
    minHeight: 60,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    paddingVertical: spacing.xs
  },
  pressed: { opacity: 0.6 },
  icon: {
    width: 44,
    height: 44,
    borderRadius: radius.control,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.background.screen
  },
  text: { flex: 1, gap: 2 }
}))
