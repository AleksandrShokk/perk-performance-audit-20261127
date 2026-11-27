import * as Haptics from 'expo-haptics'
import { useState } from 'react'
import { Pressable, View } from 'react-native'
import Animated, { useAnimatedStyle, withTiming } from 'react-native-reanimated'

import { motion } from '@app/tokens'

import { Text } from './Text'
import { createStyles } from '@/theme'

export type SegmentOption<Value extends string | number> = {
  value: Value
  label: string
}

type SegmentedControlProps<Value extends string | number> = {
  options: readonly SegmentOption<Value>[]
  value: Value
  onChange: (value: Value) => void
}

const INSET = 4

/** Стеклянная капсула с равными сегментами; выбранный — карточка с тенью. */
export function SegmentedControl<Value extends string | number>({
  options,
  value,
  onChange
}: SegmentedControlProps<Value>) {
  const styles = useStyles()
  const [width, setWidth] = useState(0)
  const segment = width ? (width - INSET * 2) / options.length : 0
  const selected = options.findIndex(option => option.value === value)

  const thumb = useAnimatedStyle(() => ({
    width: segment,
    transform: [
      {
        translateX: withTiming(Math.max(selected, 0) * segment, {
          duration: motion.fast
        })
      }
    ]
  }))

  return (
    <View
      accessibilityRole='tablist'
      onLayout={event => setWidth(event.nativeEvent.layout.width)}
      style={styles.track}
    >
      {segment > 0 && selected >= 0 && (
        <Animated.View style={[styles.thumb, thumb]} />
      )}
      {options.map(option => {
        const isSelected = option.value === value
        return (
          <Pressable
            key={String(option.value)}
            accessibilityRole='tab'
            accessibilityState={{ selected: isSelected }}
            onPress={() => {
              if (isSelected) return
              void Haptics.selectionAsync()
              onChange(option.value)
            }}
            style={styles.segment}
          >
            <Text
              variant={isSelected ? 'bodyStrong' : 'body'}
              tone={isSelected ? 'primary' : 'secondary'}
              numberOfLines={1}
            >
              {option.label}
            </Text>
          </Pressable>
        )
      })}
    </View>
  )
}

const useStyles = createStyles(({ colors, radius, sizes }) => ({
  track: {
    flexDirection: 'row',
    padding: INSET,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.glass
  },
  thumb: {
    position: 'absolute',
    top: INSET,
    bottom: INSET,
    left: INSET,
    borderRadius: radius.pill,
    backgroundColor: colors.background.card,
    boxShadow: [
      { offsetX: 0, offsetY: 4, blurRadius: 14, color: colors.shadow }
    ]
  },
  segment: {
    flex: 1,
    minHeight: sizes.touchTarget,
    alignItems: 'center',
    justifyContent: 'center'
  }
}))
