import { StyleSheet, View, type ViewProps } from 'react-native'

import { createStyles } from '@/theme'

export type CardProps = ViewProps & {
  /** Лавандовая подложка для главной карточки или действия. */
  tone?: 'default' | 'accent'
  padded?: boolean
}

export function Card({
  tone = 'default',
  padded = true,
  style,
  children,
  ...props
}: CardProps) {
  const styles = useStyles()
  return (
    <View
      {...props}
      style={[styles.card, padded && styles.padded, style]}
    >
      {tone === 'accent' && (
        <View
          pointerEvents='none'
          style={styles.accent}
        />
      )}
      {children}
    </View>
  )
}

const useStyles = createStyles(({ colors, radius, gaps }) => ({
  card: {
    backgroundColor: colors.background.card,
    borderRadius: radius.card,
    overflow: 'hidden'
  },
  padded: { padding: gaps.cardPadding },
  accent: { ...StyleSheet.absoluteFill, backgroundColor: colors.accentSoft }
}))
