import Svg, { G, Path, Rect } from 'react-native-svg'

import { useTheme } from '@/theme'

type LogoProps = { height?: number }

/** Знак и надпись PERK (assets/perk-logo.svg); надпись меняет цвет с темой. */
export function Logo({ height = 28 }: LogoProps) {
  const { colors } = useTheme()
  return (
    <Svg
      width={height * 4}
      height={height}
      viewBox='0 0 256 64'
      accessibilityRole='image'
      accessibilityLabel='PERK'
    >
      <G
        fill={colors.accent}
        transform='rotate(-12 32 32)'
      >
        <Rect
          x={8}
          y={8}
          width={21}
          height={21}
          rx={7.5}
        />
        <Rect
          x={35}
          y={8}
          width={21}
          height={21}
          rx={7.5}
          opacity={0.6}
        />
        <Rect
          x={8}
          y={35}
          width={21}
          height={21}
          rx={7.5}
          opacity={0.75}
        />
        <Rect
          x={35}
          y={35}
          width={21}
          height={21}
          rx={7.5}
        />
      </G>
      <G
        fill={colors.text.primary}
        fillRule='evenodd'
      >
        <Path d='M78 52V12h16c12 0 18 6 18 15s-6 15-18 15h-8v10Zm8-32v14h8c7 0 10-2 10-7s-3-7-10-7Z' />
        <Path d='M122 12h29v8h-21v8h19v8h-19v8h21v8h-29Z' />
        <Path d='M162 52V12h17c11 0 17 5 17 14 0 7-4 12-10 14l12 12h-11l-10-12h-7v12Zm8-32v12h9c6 0 9-2 9-6s-3-6-9-6Z' />
        <Path d='M208 12h8v17l16-17h11l-19 20 20 20h-11l-17-17v17h-8Z' />
      </G>
    </Svg>
  )
}
