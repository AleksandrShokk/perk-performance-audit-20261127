import { View } from 'react-native'

import { Text } from './Text'
import { createStyles } from '@/theme'

type AvatarProps = { name: string; size?: number }

/** Круг с первой буквой: пользователь, магазин. */
export function Avatar({ name, size = 40 }: AvatarProps) {
  const styles = useStyles()
  const letter = name.trim().charAt(0).toUpperCase() || '·'
  return (
    <View
      style={[
        styles.circle,
        { width: size, height: size, borderRadius: size / 2 }
      ]}
    >
      <Text
        variant={size >= 40 ? 'bodyStrong' : 'labelStrong'}
        tone='accent'
      >
        {letter}
      </Text>
    </View>
  )
}

const useStyles = createStyles(({ colors }) => ({
  circle: {
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.accentSoft,
    borderWidth: 1,
    borderColor: colors.border
  }
}))
