import { Check, ChevronDown } from 'lucide-react-native'
import { useState } from 'react'
import { Pressable, View } from 'react-native'

import { Text } from '@/components/ui'

import type { ChartGrouping } from '../model/chartPoints'

import { createStyles, useTheme } from '@/theme'

const OPTIONS = [
  { value: 'day', label: 'По дням' },
  { value: 'week', label: 'По неделям' },
  { value: 'month', label: 'По месяцам' }
] as const

export function GroupingSelect({
  value,
  onChange
}: {
  value: ChartGrouping
  onChange: (value: ChartGrouping) => void
}) {
  const styles = useStyles()
  const { colors } = useTheme()
  const [open, setOpen] = useState(false)
  return (
    <View style={styles.root}>
      <Pressable
        style={styles.button}
        onPress={() => setOpen(!open)}
        accessibilityRole='button'
        accessibilityState={{ expanded: open }}
        accessibilityLabel='Группировка графика'
      >
        <Text variant='label'>
          {OPTIONS.find(option => option.value === value)?.label}
        </Text>
        <ChevronDown
          size={16}
          color={colors.text.secondary}
        />
      </Pressable>
      {open && (
        <View style={styles.menu}>
          {OPTIONS.map(option => (
            <Pressable
              key={option.value}
              style={styles.option}
              accessibilityRole='button'
              accessibilityState={{ selected: option.value === value }}
              onPress={() => {
                onChange(option.value)
                setOpen(false)
              }}
            >
              <Text variant='label'>{option.label}</Text>
              {option.value === value && (
                <Check
                  size={16}
                  color={colors.accent}
                />
              )}
            </Pressable>
          ))}
        </View>
      )}
    </View>
  )
}

const useStyles = createStyles(({ colors, radius, spacing, sizes }) => ({
  root: { alignSelf: 'flex-end', zIndex: 10 },
  button: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    minHeight: sizes.touchTarget,
    paddingHorizontal: spacing.sm,
    borderRadius: radius.control,
    backgroundColor: colors.background.screen
  },
  menu: {
    position: 'absolute',
    top: sizes.touchTarget,
    right: 0,
    width: 185,
    borderRadius: radius.control,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.background.card,
    elevation: 4
  },
  option: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    minHeight: sizes.touchTarget,
    paddingHorizontal: spacing.md
  }
}))
