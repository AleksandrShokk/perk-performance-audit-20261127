import {
  type ColorScheme,
  alpha,
  gaps,
  overlay,
  palette,
  radius,
  sizes,
  spacing,
  typography
} from '@app/tokens'

function createTheme(scheme: ColorScheme) {
  const base = palette[scheme]
  const isDark = scheme === 'dark'

  return {
    scheme,
    isDark,
    colors: {
      ...base,
      /** Лавандовая подложка: главная карточка, выбранный сегмент, иконки. */
      accentSoft: alpha(base.accent, overlay[scheme].accentSoft),
      successSoft: alpha(base.success, isDark ? 0.16 : 0.12),
      errorSoft: alpha(base.error, isDark ? 0.16 : 0.1),
      /** Текст на акцентной кнопке. */
      onAccent: isDark ? base.background.screen : base.background.card,
      /** Подложка «стекла» там, где нет системного эффекта. */
      glass: alpha(base.background.card, overlay[scheme].glass),
      shadow: isDark
        ? alpha(base.background.screen, 0.65)
        : alpha(base.text.primary, 0.09),
      skeleton: alpha(base.text.secondary, isDark ? 0.18 : 0.12)
    },
    spacing,
    gaps,
    radius,
    sizes,
    typography
  } as const
}

export type Theme = ReturnType<typeof createTheme>

export const themes: Record<ColorScheme, Theme> = {
  light: createTheme('light'),
  dark: createTheme('dark')
}
