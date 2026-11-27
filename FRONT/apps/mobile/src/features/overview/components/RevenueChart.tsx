import { Fragment, useState } from 'react'
import { Pressable, View } from 'react-native'
import Svg, { Circle, Defs, LinearGradient, Path, Stop } from 'react-native-svg'

import { Text } from '@/components/ui'

import { formatMoney } from '@/lib/format'

import { chartSegments } from '../model/chartGeometry'
import { pointLabel } from '../model/chartLabels'
import type { ChartGrouping, ChartPoint } from '../model/chartPoints'

import { createStyles, useTheme } from '@/theme'

type Props = { points: ChartPoint[]; currency: string; grouping: ChartGrouping }
const HEIGHT = 150
const PAD = 6

/** Пропуск — разрыв линии, а не нулевые продажи. Number используется лишь для координат. */
export function RevenueChart({ points, currency, grouping }: Props) {
  const styles = useStyles()
  const { colors } = useTheme()
  const [width, setWidth] = useState(0)
  const [selected, setSelected] = useState<number | null>(null)
  const values = points.flatMap(point =>
    point.value === null ? [] : [point.value]
  )
  const min = Math.min(0, ...values)
  const max = Math.max(1, ...values)
  const plotWidth = Math.max(width - PAD * 2, 1)
  // Одна точка (например, «месяц» за 7 дней) стоит по центру, а не у края.
  const x = (index: number) =>
    points.length === 1
      ? width / 2
      : PAD + (index * plotWidth) / (points.length - 1)
  const y = (value: number) => 8 + ((max - value) / (max - min)) * (HEIGHT - 16)
  const segments = chartSegments(points, x, y)
  const index = selected !== null && selected < points.length ? selected : null
  const point = index === null ? undefined : points[index]
  const labels = [
    ...new Set([0, Math.floor((points.length - 1) / 2), points.length - 1])
  ].filter(position => position >= 0)

  return (
    <View style={styles.container}>
      <Text
        variant='caption'
        tone='secondary'
        style={styles.selection}
      >
        {point
          ? `${pointLabel(point, grouping)} · ${formatMoney(point.amount, currency)}${point.partial ? ' · неполные данные' : ''}`
          : 'Нажмите на график, чтобы увидеть сумму'}
      </Text>
      <Pressable
        onLayout={event => setWidth(event.nativeEvent.layout.width)}
        accessibilityLabel='График выручки. Нажмите для просмотра суммы.'
        accessibilityRole='button'
        onPress={event => {
          if (points.length === 1) return setSelected(0)
          const position = Math.round(
            ((event.nativeEvent.locationX - PAD) / plotWidth) *
              (points.length - 1)
          )
          setSelected(Math.max(0, Math.min(points.length - 1, position)))
        }}
      >
        {width > 0 && (
          <Svg
            width={width}
            height={HEIGHT}
          >
            <Defs>
              <LinearGradient
                id='revenue-fill'
                x1='0'
                y1='0'
                x2='0'
                y2='1'
              >
                <Stop
                  offset='0'
                  stopColor={colors.accent}
                  stopOpacity={0.12}
                />
                <Stop
                  offset='1'
                  stopColor={colors.accent}
                  stopOpacity={0.01}
                />
              </LinearGradient>
            </Defs>
            {[0, 0.5, 1].map(fraction => (
              <Path
                key={fraction}
                d={`M0,${8 + fraction * (HEIGHT - 16)} H${width}`}
                stroke={colors.border}
              />
            ))}
            {segments.map((segment, key) => (
              <Fragment key={key}>
                <Path
                  d={segment.area}
                  fill='url(#revenue-fill)'
                />
                <Path
                  d={segment.line}
                  stroke={colors.accent}
                  strokeWidth={2.5}
                  fill='none'
                  strokeLinecap='round'
                  strokeLinejoin='round'
                />
                {segment.isolated && (
                  <Circle
                    cx={segment.isolated.x}
                    cy={segment.isolated.y}
                    r={4}
                    fill={colors.accent}
                  />
                )}
              </Fragment>
            ))}
            {point?.value != null && index !== null && (
              <Circle
                cx={x(index)}
                cy={y(point.value)}
                r={5}
                fill={colors.background.card}
                stroke={colors.accent}
                strokeWidth={2.5}
              />
            )}
          </Svg>
        )}
      </Pressable>
      <View
        style={[styles.caption, labels.length === 1 && styles.captionCentered]}
      >
        {labels.map(position => (
          <Text
            key={position}
            variant='caption'
            tone='secondary'
          >
            {points[position]
              ? pointLabel(points[position], grouping, true)
              : ''}
          </Text>
        ))}
      </View>
    </View>
  )
}

const useStyles = createStyles(({ spacing }) => ({
  container: { gap: spacing.xs, marginVertical: spacing.md },
  selection: { minHeight: 18 },
  caption: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.xxs,
    justifyContent: 'space-between'
  },
  captionCentered: { justifyContent: 'center' }
}))
