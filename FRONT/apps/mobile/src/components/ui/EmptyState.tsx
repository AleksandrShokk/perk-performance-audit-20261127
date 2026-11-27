import type { LucideIcon } from 'lucide-react-native'
import { View } from 'react-native'

import { Button } from './Button'
import { Text } from './Text'
import { createStyles, useTheme } from '@/theme'

type EmptyStateProps = {
  icon: LucideIcon
  title: string
  description?: string
  actionTitle?: string
  onAction?: () => void
}

/** Пустой период, раздел в разработке, нет подключённого магазина. */
export function EmptyState({
  icon: Icon,
  title,
  description,
  actionTitle,
  onAction
}: EmptyStateProps) {
  const styles = useStyles()
  const { colors } = useTheme()
  return (
    <View style={styles.wrapper}>
      <View style={styles.icon}>
        <Icon
          size={28}
          color={colors.accent}
        />
      </View>
      <Text
        variant='sectionTitle'
        align='center'
      >
        {title}
      </Text>
      {description && (
        <Text
          tone='secondary'
          align='center'
        >
          {description}
        </Text>
      )}
      {actionTitle && onAction && (
        <Button
          title={actionTitle}
          onPress={onAction}
          block={false}
        />
      )}
    </View>
  )
}

const useStyles = createStyles(({ colors, radius, spacing }) => ({
  wrapper: {
    alignItems: 'center',
    gap: spacing.sm,
    paddingVertical: spacing.xxl
  },
  icon: {
    width: 64,
    height: 64,
    borderRadius: radius.card,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.accentSoft,
    marginBottom: spacing.xs
  }
}))
