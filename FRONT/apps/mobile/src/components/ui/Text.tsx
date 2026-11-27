import {
  Text as NativeText,
  type TextProps as NativeTextProps
} from 'react-native'

import type { TypographyVariant } from '@app/tokens'

import { type Theme, useTheme } from '@/theme'

export type TextTone =
  'primary' | 'secondary' | 'accent' | 'success' | 'error' | 'onAccent'

export type TextProps = NativeTextProps & {
  variant?: TypographyVariant
  tone?: TextTone
  align?: 'left' | 'center' | 'right'
  /** Цифры одинаковой ширины — для сумм и таблиц. */
  tabular?: boolean
}

function toneColor({ colors }: Theme, tone: TextTone) {
  switch (tone) {
    case 'primary':
      return colors.text.primary
    case 'secondary':
      return colors.text.secondary
    case 'onAccent':
      return colors.onAccent
    default:
      return colors[tone]
  }
}

export function Text({
  variant = 'body',
  tone = 'primary',
  align,
  tabular,
  style,
  ...props
}: TextProps) {
  const theme = useTheme()
  return (
    <NativeText
      maxFontSizeMultiplier={1.6}
      {...props}
      style={[
        theme.typography[variant],
        { color: toneColor(theme, tone) },
        align && { textAlign: align },
        tabular && { fontVariant: ['tabular-nums'] },
        style
      ]}
    />
  )
}
