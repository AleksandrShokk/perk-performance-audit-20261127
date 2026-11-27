/** Шкала расстояний 4…48 (PERK-DESIGN.md → «Размеры, отступы и скругления»). */
export const spacing = {
  xxs: 4,
  xs: 8,
  sm: 12,
  md: 16,
  lg: 20,
  xl: 24,
  xxl: 32,
  xxxl: 40,
  huge: 48
} as const

/** Смысловые отступы: что использовать в типичных местах. */
export const gaps = {
  betweenItems: spacing.xs,
  betweenCards: spacing.md,
  betweenSections: spacing.xl,
  screenPadding: spacing.lg,
  cardPadding: spacing.lg
} as const

export const radius = {
  chip: 10,
  control: 14,
  card: 24,
  sheet: 28,
  pill: 999
} as const

export const sizes = {
  control: 50,
  button: 48,
  touchTarget: 48,
  icon: 20,
  iconLarge: 24,
  avatar: 40,
  hairline: 1
} as const
