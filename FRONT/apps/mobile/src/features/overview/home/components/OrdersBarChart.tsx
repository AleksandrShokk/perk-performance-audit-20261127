import { useState } from 'react'
import { Pressable, View } from 'react-native'
import { GestureDetector } from 'react-native-gesture-handler'
import Svg, { G, Line, Rect, Text as SvgText } from 'react-native-svg'

import { alpha } from '@app/tokens'

import { Text } from '@/components/ui'

import { formatLongDate, formatNumber, formatShortDate } from '@/lib/format'

import { useChartDaySelection } from '../hooks/useChartDaySelection'
import { formatOrderValue } from '../model/overviewMetrics'
import type {
  ChartComparison,
  ChartUnit,
  OrderBarPoint
} from '../model/overviewTypes'

import { createStyles, useTheme } from '@/theme'

const HEIGHT = 168
const TOP = 12
const BOTTOM = 146
const AXIS_WIDTH = 40

function axisLabel(value: number) {
  if (value >= 1_000_000) return `${formatNumber(value / 1_000_000, 1)} млн`
  if (value >= 1000) return `${formatNumber(value / 1000, 0)} тыс.`
  return formatNumber(value)
}

export function OrdersBarChart({
  points,
  comparison,
  unit,
  currency
}: {
  points: OrderBarPoint[]
  comparison: ChartComparison
  unit: ChartUnit
  currency?: string | null
}) {
  const styles = useStyles()
  const { colors } = useTheme()
  const [width, setWidth] = useState(0)
  const other = (point: OrderBarPoint) =>
    comparison === 'buyouts' ? point.buyouts : point.previousOrdered
  const maximum =
    Math.max(
      1,
      ...points.flatMap(point => [
        Number(point.ordered ?? 0),
        Number(other(point) ?? 0)
      ])
    ) * 1.08
  const plotWidth = Math.max(1, width - AXIS_WIDTH)
  const { selected, selectAt, gesture } = useChartDaySelection(
    points.length,
    width - AXIS_WIDTH
  )
  const cell = plotWidth / Math.max(1, points.length)
  const barWidth = Math.min(18, cell * 0.66)
  const y = (value: number) =>
    BOTTOM - (Math.max(0, value) / maximum) * (BOTTOM - TOP)
  const muted = alpha(colors.text.secondary, 0.22)
  const primary = comparison === 'previous' ? colors.accent : muted
  const secondary = comparison === 'previous' ? muted : colors.accent
  const point = selected == null ? undefined : points[selected]
  const labels = [
    ...new Set([0, Math.floor((points.length - 1) / 2), points.length - 1])
  ]
  const hasData = points.some(
    point => point.ordered != null || other(point) != null
  )

  return (
    <View style={styles.root}>
      <View style={styles.legend}>
        <Legend
          color={primary}
          label='Заказано'
        />
        <Legend
          color={secondary}
          label={comparison === 'previous' ? 'Прошлый период' : 'Выкуплено'}
        />
      </View>
      <View
        style={styles.selection}
        accessibilityLiveRegion='polite'
      >
        {point ? (
          <>
            <Text
              variant='caption'
              tone='secondary'
            >
              {formatLongDate(point.day)}
            </Text>
            <Text variant='caption'>
              Заказано: {formatOrderValue(point.ordered, unit, currency)}
              {unit === 'amount' && point.orderedUnits != null
                ? ` · ${formatNumber(point.orderedUnits)} шт.`
                : ''}
            </Text>
            <Text variant='caption'>
              {comparison === 'buyouts'
                ? `Выкуплено: ${formatOrderValue(point.buyouts, unit, currency)}${unit === 'amount' && point.buyoutUnits != null ? ` · ${formatNumber(point.buyoutUnits)} шт.` : ''}`
                : `${formatShortDate(point.previousDay)}: ${formatOrderValue(point.previousOrdered, unit, currency)}`}
            </Text>
          </>
        ) : (
          <Text
            variant='caption'
            tone='secondary'
          >
            Выберите день
          </Text>
        )}
      </View>
      <GestureDetector
        gesture={gesture}
        touchAction='pan-y'
      >
        <Pressable
          onLayout={event => setWidth(event.nativeEvent.layout.width)}
          accessibilityRole='button'
          accessibilityLabel='Столбчатый график заказов. Нажмите или ведите пальцем для выбора дня.'
          onPress={event => {
            // Native передаёт locationX, браузерный click — offsetX.
            const touch = event.nativeEvent
            const position = Number.isFinite(touch.locationX)
              ? touch.locationX
              : 'offsetX' in touch && typeof touch.offsetX === 'number'
                ? touch.offsetX
                : 0
            selectAt(position)
          }}
        >
          <Svg
            pointerEvents='none'
            width={Math.max(1, width)}
            height={HEIGHT}
          >
            {[0, 0.5, 1].map(fraction => (
              <ViewRule
                key={fraction}
                value={maximum * fraction}
                y={y(maximum * fraction)}
                width={plotWidth}
                color={colors.border}
                textColor={colors.text.secondary}
              />
            ))}
            {points.map((item, index) => {
              const center = cell * (index + 0.5)
              const isSelected = selected === index
              const bar = (
                value: string | null,
                fill: string,
                x: number,
                size: number
              ) => {
                if (value == null) return null
                const top = y(Number(value))
                return (
                  <Rect
                    x={x}
                    y={top}
                    width={size}
                    height={Math.max(1, BOTTOM - top)}
                    rx={Math.min(4, size / 2)}
                    fill={fill}
                    opacity={selected == null || isSelected ? 1 : 0.55}
                  />
                )
              }
              return (
                <G key={item.day}>
                  {isSelected && (
                    <Line
                      x1={center}
                      x2={center}
                      y1={TOP}
                      y2={BOTTOM}
                      stroke={colors.accent}
                      strokeDasharray='3 3'
                    />
                  )}
                  {comparison === 'buyouts' ? (
                    <>
                      {bar(
                        item.ordered,
                        primary,
                        center - barWidth / 2,
                        barWidth
                      )}
                      {bar(
                        item.buyouts,
                        secondary,
                        center - barWidth * 0.32,
                        barWidth * 0.64
                      )}
                    </>
                  ) : (
                    <>
                      {bar(
                        item.previousOrdered,
                        secondary,
                        center - barWidth / 2,
                        barWidth / 2
                      )}
                      {bar(item.ordered, primary, center, barWidth / 2)}
                    </>
                  )}
                </G>
              )
            })}
            {!hasData && (
              <SvgText
                x={plotWidth / 2}
                y={HEIGHT / 2}
                textAnchor='middle'
                fontSize={12}
                fill={colors.text.secondary}
              >
                Данные ещё не получены
              </SvgText>
            )}
          </Svg>
        </Pressable>
      </GestureDetector>
      <View style={[styles.labels, { marginRight: AXIS_WIDTH }]}>
        {labels
          .filter(index => index >= 0)
          .map(index => (
            <Text
              key={index}
              variant='caption'
              tone='secondary'
            >
              {points[index] ? formatShortDate(points[index]!.day) : ''}
            </Text>
          ))}
      </View>
    </View>
  )
}

function ViewRule({
  value,
  y,
  width,
  color,
  textColor
}: {
  value: number
  y: number
  width: number
  color: string
  textColor: string
}) {
  return (
    <>
      <Line
        x1={0}
        x2={width}
        y1={y}
        y2={y}
        stroke={color}
        strokeDasharray='3 4'
      />
      <SvgText
        x={width + 6}
        y={y + 3}
        fontSize={9}
        fill={textColor}
      >
        {axisLabel(value)}
      </SvgText>
    </>
  )
}

function Legend({ color, label }: { color: string; label: string }) {
  const styles = useStyles()
  return (
    <View style={styles.legendItem}>
      <View style={[styles.dot, { backgroundColor: color }]} />
      <Text
        variant='caption'
        tone='secondary'
      >
        {label}
      </Text>
    </View>
  )
}

const useStyles = createStyles(({ spacing, radius }) => ({
  root: { gap: spacing.xs },
  legend: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.md },
  legendItem: { flexDirection: 'row', alignItems: 'center', gap: spacing.xxs },
  dot: { width: spacing.xs, height: spacing.xs, borderRadius: radius.pill },
  selection: { minHeight: 58, justifyContent: 'center', gap: 2 },
  labels: { flexDirection: 'row', justifyContent: 'space-between' }
}))
