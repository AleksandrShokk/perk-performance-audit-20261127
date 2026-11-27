import {
  CircleAlert,
  CircleCheck,
  Info,
  type LucideIcon
} from 'lucide-react-native'
import { View } from 'react-native'

import { Button } from './Button'
import { Text } from './Text'
import { createStyles, useTheme } from '@/theme'

type NoticeTone = 'info' | 'success' | 'error'

type NoticeProps = {
  message: string
  title?: string
  tone?: NoticeTone
  actionTitle?: string
  onAction?: () => void
}

const ICONS: Record<NoticeTone, LucideIcon> = {
  info: Info,
  success: CircleCheck,
  error: CircleAlert
}

/** Короткое сообщение в потоке экрана: ошибка формы, статус загрузки, предупреждение. */
export function Notice({
  message,
  title,
  tone = 'info',
  actionTitle,
  onAction
}: NoticeProps) {
  const styles = useStyles()
  const { colors } = useTheme()
  const Icon = ICONS[tone]
  const color = tone === 'info' ? colors.accent : colors[tone]

  return (
    <View
      accessibilityRole={tone === 'error' ? 'alert' : undefined}
      style={[styles.notice, styles[tone]]}
    >
      <Icon
        size={20}
        color={color}
      />
      <View style={styles.body}>
        {title && <Text variant='bodyStrong'>{title}</Text>}
        <Text variant='label'>{message}</Text>
        {actionTitle && onAction && (
          <View style={styles.action}>
            <Button
              title={actionTitle}
              variant='ghost'
              onPress={onAction}
            />
          </View>
        )}
      </View>
    </View>
  )
}

const useStyles = createStyles(({ colors, radius, spacing }) => ({
  notice: {
    flexDirection: 'row',
    gap: spacing.sm,
    padding: spacing.md,
    borderRadius: radius.control
  },
  info: { backgroundColor: colors.accentSoft },
  success: { backgroundColor: colors.successSoft },
  error: { backgroundColor: colors.errorSoft },
  body: { flex: 1, gap: spacing.xxs },
  action: {
    alignItems: 'flex-start',
    marginLeft: -spacing.sm,
    marginTop: spacing.xxs
  }
}))
