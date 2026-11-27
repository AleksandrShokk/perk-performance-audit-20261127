import { ArrowRight } from 'lucide-react-native'
import { Pressable, View } from 'react-native'

import { Text } from './Text'
import { createStyles, useTheme } from '@/theme'

type SectionHeaderProps = {
  title: string
  actionTitle?: string
  onAction?: () => void
}

/** Заголовок раздела с необязательной ссылкой «Все →». */
export function SectionHeader({
  title,
  actionTitle,
  onAction
}: SectionHeaderProps) {
  const styles = useStyles()
  const { colors } = useTheme()
  return (
    <View style={styles.row}>
      <Text
        variant='sectionTitle'
        accessibilityRole='header'
      >
        {title}
      </Text>
      {actionTitle && onAction && (
        <Pressable
          accessibilityRole='link'
          hitSlop={12}
          onPress={onAction}
          style={styles.action}
        >
          <Text
            variant='label'
            tone='secondary'
          >
            {actionTitle}
          </Text>
          <ArrowRight
            size={16}
            color={colors.text.secondary}
          />
        </Pressable>
      )}
    </View>
  )
}

const useStyles = createStyles(({ spacing, sizes }) => ({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: spacing.xs
  },
  action: {
    minHeight: sizes.touchTarget,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xxs
  }
}))
