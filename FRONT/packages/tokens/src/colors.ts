/**
 * Палитры PERK (PERK-DESIGN.md → «Цвета»). У тёмной темы те же роли, другие значения.
 * Подложки и стекло получаются из этих же цветов через прозрачность — см. `alpha`.
 */
export const palette = {
  light: {
    background: { screen: '#F7F7FB', card: '#FFFFFF' },
    text: { primary: '#242436', secondary: '#6B6B80' },
    border: '#E5E5F0',
    accent: '#625DD5',
    success: '#25775D',
    error: '#B23A4B'
  },
  dark: {
    background: { screen: '#16161E', card: '#22222E' },
    text: { primary: '#F4F4F8', secondary: '#A8A8BC' },
    border: '#363647',
    accent: '#A5A0FF',
    success: '#76D1B1',
    error: '#FF9CA8'
  }
} as const

export type ColorScheme = keyof typeof palette
export type Palette = (typeof palette)[ColorScheme]

/** Прозрачность для подложек: лавандовая карточка — 8% (светлая) и 12% (тёмная). */
export const overlay = {
  light: { accentSoft: 0.08, glass: 0.7 },
  dark: { accentSoft: 0.12, glass: 0.85 }
} as const satisfies Record<ColorScheme, Record<string, number>>

/** `#RRGGBB` + непрозрачность 0–1 → `#RRGGBBAA`. */
export function alpha(hex: string, opacity: number) {
  const channel = Math.round(Math.min(Math.max(opacity, 0), 1) * 255)
  return `${hex}${channel.toString(16).padStart(2, '0').toUpperCase()}`
}
