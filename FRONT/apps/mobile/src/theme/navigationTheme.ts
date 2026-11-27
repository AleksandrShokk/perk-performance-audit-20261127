import {
  DarkTheme,
  DefaultTheme,
  type Theme as NavigationTheme
} from 'expo-router'

import type { Theme } from './theme'

/** Цвета PERK для системной навигации: фон экранов, заголовки, акцент. */
export function navigationTheme({ isDark, colors }: Theme): NavigationTheme {
  const base = isDark ? DarkTheme : DefaultTheme
  return {
    ...base,
    colors: {
      ...base.colors,
      background: colors.background.screen,
      card: colors.background.card,
      text: colors.text.primary,
      border: colors.border,
      primary: colors.accent,
      notification: colors.accent
    }
  }
}
