/**
 * Текстовые роли (PERK-DESIGN.md → «Шрифты»). Системный шрифт: SF Pro на iOS,
 * Roboto на Android. 700 — только для логотипа.
 */
export const typography = {
  screenTitle: {
    fontSize: 30,
    lineHeight: 36,
    fontWeight: '600',
    letterSpacing: -0.5
  },
  mainValue: {
    fontSize: 36,
    lineHeight: 42,
    fontWeight: '600',
    letterSpacing: -1
  },
  sectionTitle: {
    fontSize: 18,
    lineHeight: 24,
    fontWeight: '600',
    letterSpacing: 0
  },
  value: {
    fontSize: 20,
    lineHeight: 26,
    fontWeight: '600',
    letterSpacing: -0.3
  },
  body: { fontSize: 16, lineHeight: 23, fontWeight: '400', letterSpacing: 0 },
  bodyStrong: {
    fontSize: 16,
    lineHeight: 23,
    fontWeight: '500',
    letterSpacing: 0
  },
  label: { fontSize: 14, lineHeight: 20, fontWeight: '400', letterSpacing: 0 },
  labelStrong: {
    fontSize: 14,
    lineHeight: 20,
    fontWeight: '500',
    letterSpacing: 0
  },
  caption: { fontSize: 12, lineHeight: 17, fontWeight: '400', letterSpacing: 0 }
} as const

export type TypographyVariant = keyof typeof typography
