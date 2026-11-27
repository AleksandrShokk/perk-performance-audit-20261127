import {
  type ImageStyle,
  StyleSheet,
  type TextStyle,
  type ViewStyle
} from 'react-native'

import type { ColorScheme } from '@app/tokens'

import type { Theme } from './theme'
import { useTheme } from './useTheme'

type NamedStyles<T> = { [Key in keyof T]: ViewStyle | TextStyle | ImageStyle }

/**
 * Описывает стили компонента через тему. Таблица создаётся один раз на тему.
 *
 * const useStyles = createStyles(({ colors, spacing }) => ({
 *   card: { backgroundColor: colors.background.card, padding: spacing.lg }
 * }))
 * …
 * const styles = useStyles()
 */
export function createStyles<T extends NamedStyles<T>>(
  factory: (theme: Theme) => T
) {
  const cache = new Map<ColorScheme, T>()

  return function useStyles(): T {
    const theme = useTheme()
    let styles = cache.get(theme.scheme)
    if (!styles) {
      styles = StyleSheet.create(factory(theme))
      cache.set(theme.scheme, styles)
    }
    return styles
  }
}
