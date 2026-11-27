import { addMonths, format, parseISO, startOfMonth } from 'date-fns'
import { ru } from 'date-fns/locale'
import { ChevronLeft, ChevronRight } from 'lucide-react-native'
import { useState } from 'react'
import { Pressable, View } from 'react-native'

import { Text } from '@/components/ui'

import { type DateRange, HISTORY_START, lastDays, toISODate } from '@/lib/dates'

import { calendarDays } from '../model/calendarDays'
import { rangeError } from '../model/periodRange'

import { createStyles, useTheme } from '@/theme'

/** Один календарь для главной и подробных отчётов. Даты включают оба края. */
export function DateRangeEditor({
  value,
  onChange,
  maxDays
}: {
  value: DateRange
  onChange: (range: DateRange) => void
  maxDays?: number
}) {
  const styles = useStyles()
  const { colors } = useTheme()
  const [edge, setEdge] = useState<'date_from' | 'date_to'>('date_from')
  const [month, setMonth] = useState(() =>
    startOfMonth(parseISO(value.date_to))
  )
  const maxDate = lastDays(1).date_to
  const error = rangeError(value, maxDays, maxDate)
  const days = calendarDays(month)

  function choose(day: string) {
    if (edge === 'date_from') {
      onChange({
        date_from: day,
        date_to: day > value.date_to ? day : value.date_to
      })
      setEdge('date_to')
    } else {
      onChange({
        date_from: day < value.date_from ? day : value.date_from,
        date_to: day
      })
    }
  }

  return (
    <View style={styles.calendar}>
      <View style={styles.edges}>
        {(['date_from', 'date_to'] as const).map(key => {
          const label = `${key === 'date_from' ? 'С' : 'По'} ${format(parseISO(value[key]), 'dd.MM.yyyy')}`
          return (
            <Pressable
              key={key}
              accessibilityRole='button'
              accessibilityLabel={label}
              accessibilityState={{ selected: edge === key }}
              onPress={() => {
                setEdge(key)
                setMonth(startOfMonth(parseISO(value[key])))
              }}
              style={[styles.edge, edge === key && styles.active]}
            >
              <Text variant='labelStrong'>{label}</Text>
            </Pressable>
          )
        })}
      </View>
      <View style={styles.month}>
        <Pressable
          accessibilityRole='button'
          accessibilityLabel='Предыдущий месяц'
          disabled={toISODate(month) <= HISTORY_START.slice(0, 7) + '-01'}
          onPress={() => setMonth(addMonths(month, -1))}
          style={styles.arrow}
        >
          <ChevronLeft
            size={20}
            color={colors.text.secondary}
          />
        </Pressable>
        <Text variant='bodyStrong'>
          {format(month, 'LLLL yyyy', { locale: ru })}
        </Text>
        <Pressable
          accessibilityRole='button'
          accessibilityLabel='Следующий месяц'
          disabled={toISODate(month).slice(0, 7) >= maxDate.slice(0, 7)}
          onPress={() => setMonth(addMonths(month, 1))}
          style={styles.arrow}
        >
          <ChevronRight
            size={20}
            color={colors.text.secondary}
          />
        </Pressable>
      </View>
      <View style={styles.grid}>
        {['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'].map(day => (
          <View
            key={day}
            style={styles.cell}
          >
            <Text
              variant='caption'
              tone='secondary'
            >
              {day}
            </Text>
          </View>
        ))}
        {days.map(day => {
          const iso = toISODate(day)
          const disabled = iso < HISTORY_START || iso > maxDate
          const boundary = iso === value.date_from || iso === value.date_to
          const inside = iso >= value.date_from && iso <= value.date_to
          return (
            <Pressable
              key={iso}
              accessibilityRole='button'
              accessibilityLabel={format(day, 'd MMMM yyyy', { locale: ru })}
              accessibilityState={{ selected: inside, disabled }}
              disabled={disabled}
              onPress={() => choose(iso)}
              style={[
                styles.cell,
                inside && styles.inside,
                boundary && styles.active,
                (disabled || day.getMonth() !== month.getMonth()) &&
                  styles.muted
              ]}
            >
              <Text
                variant={boundary ? 'bodyStrong' : 'body'}
                tone={inside ? 'accent' : 'primary'}
              >
                {format(day, 'd')}
              </Text>
            </Pressable>
          )
        })}
      </View>
      {error && (
        <Text
          variant='caption'
          tone='error'
          accessibilityRole='alert'
        >
          {error}
        </Text>
      )}
    </View>
  )
}

const useStyles = createStyles(({ colors, spacing, radius, sizes }) => ({
  calendar: { gap: spacing.sm },
  edges: { flexDirection: 'row', gap: spacing.sm },
  edge: {
    flex: 1,
    minHeight: sizes.touchTarget,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.background.screen,
    borderRadius: radius.control,
    borderWidth: 1,
    borderColor: 'transparent'
  },
  active: { backgroundColor: colors.accentSoft, borderColor: colors.accent },
  month: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between'
  },
  arrow: {
    width: sizes.touchTarget,
    height: sizes.touchTarget,
    alignItems: 'center',
    justifyContent: 'center'
  },
  grid: { flexDirection: 'row', flexWrap: 'wrap' },
  cell: {
    width: '14.285714%',
    minHeight: sizes.touchTarget,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: 'transparent',
    borderRadius: radius.control
  },
  inside: { backgroundColor: colors.accentSoft },
  muted: { opacity: 0.3 }
}))
