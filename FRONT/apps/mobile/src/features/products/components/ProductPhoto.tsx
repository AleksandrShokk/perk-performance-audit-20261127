import { Image } from 'expo-image'
import { Package } from 'lucide-react-native'
import { useState } from 'react'
import { type StyleProp, View, type ViewStyle } from 'react-native'

import { createStyles, useTheme } from '@/theme'

export function ProductPhoto({
  uri,
  label,
  style
}: {
  uri?: string
  label: string
  style?: StyleProp<ViewStyle>
}) {
  const styles = useStyles()
  const { colors } = useTheme()
  const [failed, setFailed] = useState<string>()
  return (
    <View style={[styles.frame, style]}>
      {uri && failed !== uri ? (
        <Image
          source={{ uri }}
          accessibilityLabel={label}
          style={styles.image}
          contentFit='contain'
          cachePolicy='disk'
          onError={() => setFailed(uri)}
        />
      ) : (
        <Package
          size={28}
          color={colors.text.secondary}
        />
      )}
    </View>
  )
}
const useStyles = createStyles(({ colors, radius }) => ({
  frame: {
    overflow: 'hidden',
    borderRadius: radius.control,
    backgroundColor: colors.background.screen,
    alignItems: 'center',
    justifyContent: 'center'
  },
  image: { width: '100%', height: '100%' }
}))
