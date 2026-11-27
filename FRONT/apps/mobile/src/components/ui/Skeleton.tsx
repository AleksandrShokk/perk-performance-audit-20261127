import { useEffect } from 'react'
import type { DimensionValue, StyleProp, ViewStyle } from 'react-native'
import Animated, {
  cancelAnimation,
  useAnimatedStyle,
  useSharedValue,
  withRepeat,
  withTiming
} from 'react-native-reanimated'

import { motion } from '@app/tokens'

import { createStyles } from '@/theme'

type SkeletonProps = {
  width?: DimensionValue
  height?: number
  radius?: number
  style?: StyleProp<ViewStyle>
}

/** Спокойный placeholder на месте показателя или графика, пока нет данных. */
export function Skeleton({
  width = '100%',
  height = 16,
  radius = 8,
  style
}: SkeletonProps) {
  const styles = useStyles()
  const opacity = useSharedValue(1)

  useEffect(() => {
    opacity.value = withRepeat(
      withTiming(0.45, { duration: motion.pulse }),
      -1,
      true
    )
    return () => cancelAnimation(opacity)
  }, [opacity])

  const pulse = useAnimatedStyle(() => ({ opacity: opacity.value }))

  return (
    <Animated.View
      accessibilityElementsHidden
      importantForAccessibility='no-hide-descendants'
      style={[
        styles.block,
        { width, height, borderRadius: radius },
        pulse,
        style
      ]}
    />
  )
}

const useStyles = createStyles(({ colors }) => ({
  block: { backgroundColor: colors.skeleton }
}))
