import type { LucideIcon } from 'lucide-react-native'
import { View } from 'react-native'

import { Text } from './Text'
import { createStyles, useTheme } from '@/theme'

type PillTone = 'neutral' | 'accent' | 'success' | 'error'

type PillProps = {
  label: string
  tone?: PillTone
  icon?: LucideIcon
}

/** Компактная плашка: статус, изменение, ABC-класс. Смысл передаёт текст, цвет помогает. */
export function Pill({ label, tone = 'neutral', icon: Icon }: PillProps) {
  const styles = useStyles()
  const { colors } = useTheme()
  const color = {
    neutral: colors.text.secondary,
    accent: colors.accent,
    success: colors.success,
    error: colors.error
  }[tone]

  return (
    <View style={[styles.pill, styles[tone]]}>
      {Icon && (
        <Icon
          size={14}
          color={color}
        />
      )}
      <Text
        variant='labelStrong'
        style={{ color }}
        numberOfLines={1}
      >
        {label}
      </Text>
    </View>
  )
}

const useStyles = createStyles(({ colors, radius, spacing }) => ({
  pill: {
    flexDirection: 'row',
    alignItems: 'center',
    alignSelf: 'flex-start',
    gap: spacing.xxs,
    paddingHorizontal: spacing.xs,
    paddingVertical: spacing.xxs,
    borderRadius: radius.chip
  },
  neutral: { backgroundColor: colors.background.screen },
  accent: { backgroundColor: colors.accentSoft },
  success: { backgroundColor: colors.successSoft },
  error: { backgroundColor: colors.errorSoft }
}))
