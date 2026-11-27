import { ChevronRight } from 'lucide-react-native'
import type { ReactNode } from 'react'
import { Pressable, View } from 'react-native'

import { Card, Text } from '@/components/ui'

import { createStyles, useTheme } from '@/theme'

export function SummaryCard({
  title,
  subtitle,
  action,
  onPress,
  children
}: {
  title: string
  subtitle?: string
  action?: string
  onPress?: () => void
  children: ReactNode
}) {
  const styles = useStyles()
  const { colors } = useTheme()
  return (
    <Card>
      <View style={styles.heading}>
        <Text variant='sectionTitle'>{title}</Text>
        {subtitle && (
          <Text
            variant='caption'
            tone='secondary'
          >
            {subtitle}
          </Text>
        )}
      </View>
      <View style={styles.body}>{children}</View>
      {action && (
        <Pressable
          accessibilityRole='button'
          accessibilityState={{ disabled: !onPress }}
          disabled={!onPress}
          onPress={onPress}
          style={styles.action}
        >
          <Text
            variant='labelStrong'
            tone={onPress ? 'accent' : 'secondary'}
          >
            {action}
          </Text>
          {onPress ? (
            <ChevronRight
              size={16}
              color={colors.accent}
            />
          ) : (
            <Text
              variant='caption'
              tone='secondary'
            >
              Скоро
            </Text>
          )}
        </Pressable>
      )}
    </Card>
  )
}

export function SummaryMetric({
  label,
  value,
  hint
}: {
  label: string
  value: string
  hint?: string
}) {
  const styles = useStyles()
  return (
    <View style={styles.metric}>
      <View style={styles.label}>
        <Text
          variant='caption'
          tone='secondary'
        >
          {label}
        </Text>
      </View>
      <Text
        variant='value'
        tabular
        numberOfLines={1}
        adjustsFontSizeToFit
      >
        {value}
      </Text>
      {hint && (
        <Text
          variant='caption'
          tone='secondary'
        >
          {hint}
        </Text>
      )}
    </View>
  )
}

const useStyles = createStyles(({ colors, spacing, sizes }) => ({
  heading: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: spacing.xs,
    flexWrap: 'wrap'
  },
  body: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.md,
    paddingVertical: spacing.lg
  },
  metric: { flex: 1, minWidth: 110, gap: spacing.xxs },
  label: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    flexWrap: 'wrap'
  },
  action: {
    minHeight: sizes.touchTarget,
    borderTopWidth: 1,
    borderColor: colors.border,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: spacing.xs,
    paddingTop: spacing.xs
  }
}))
