import { endOfMonth, endOfWeek, parseISO } from 'date-fns'
import { Decimal } from 'decimal.js'

import type { ProfitReport } from '@app/api'

import { type DateRange, eachDay, toISODate } from '@/lib/dates'

// До 90 денежных строк со scale до 16: стандартных 20 значащих цифр недостаточно.
const Money = Decimal.clone({ precision: 64 })

export type ChartGrouping = 'day' | 'week' | 'month'

export type ChartPoint = {
  /** Первый и последний день точки внутри выбранного периода. */
  day: string
  end: string
  /** Точная сумма для подписи; value — только координата. */
  amount: string | null
  value: number | null
  /** Часть дней точки неизвестна: сумма — по известным дням. */
  partial: boolean
}

/** Последний день группы, обрезанный концом периода. Недели — с понедельника. */
function bucketEnd(day: string, grouping: ChartGrouping, last: string) {
  if (grouping === 'day') return day
  const date = parseISO(day)
  const end = toISODate(
    grouping === 'week'
      ? endOfWeek(date, { weekStartsOn: 1 })
      : endOfMonth(date)
  )
  return end < last ? end : last
}

/**
 * Точки графика. Нулём считается только день подтверждённого полного отчёта;
 * неизвестный день — не ноль. Суммы — decimal.js, Number только для координат.
 */
export function chartPoints(
  report: ProfitReport | undefined,
  range: DateRange,
  grouping: ChartGrouping = 'day'
): ChartPoint[] {
  const rows = new Map(report?.daily?.map(day => [day.day, day]))
  const complete =
    report?.status === 'ready' && report.period_covered && !report.is_partial
  return groupChartValues(
    new Map(
      eachDay(range).map(day => {
        const row = rows.get(day)
        return [day, row ? (row.revenue ?? null) : complete ? '0' : null]
      })
    ),
    range,
    grouping
  )
}

export function groupChartValues(
  values: ReadonlyMap<string, string | null>,
  range: DateRange,
  grouping: ChartGrouping,
  partialDays: ReadonlySet<string> = new Set()
): ChartPoint[] {
  const dayValue = (day: string): Decimal | null => {
    const raw = values.get(day)
    if (raw == null) return null
    try {
      const value = new Money(raw)
      return value.isFinite() ? value : null
    } catch {
      return null
    }
  }

  const points: ChartPoint[] = []
  const days = eachDay(range)
  for (let index = 0; index < days.length;) {
    const start = days[index]!
    const end = bucketEnd(start, grouping, range.date_to)
    let sum = new Money(0)
    let known = 0
    let unknown = 0
    let partial = false
    for (; index < days.length && days[index]! <= end; index += 1) {
      const value = dayValue(days[index]!)
      partial ||= partialDays.has(days[index]!)
      if (value === null) unknown += 1
      else {
        sum = sum.plus(value)
        known += 1
      }
    }
    points.push({
      day: start,
      end,
      amount: known ? sum.toFixed() : null,
      value: known ? sum.toNumber() : null,
      partial: known > 0 && (unknown > 0 || partial)
    })
  }
  return points
}
