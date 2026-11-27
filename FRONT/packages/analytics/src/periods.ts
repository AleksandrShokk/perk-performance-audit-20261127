import { differenceInCalendarDays, isValid, parseISO } from 'date-fns'

import { type DateRange, HISTORY_START, lastDays, toISODate } from './dates'

export type ReportPeriod = number | DateRange
export const MAX_REPORT_DAYS = 1100

export function resolvePeriod(period: ReportPeriod): DateRange {
  return typeof period === 'number' ? lastDays(period) : period
}

export function rangeError(
  range: DateRange,
  maxDays = MAX_REPORT_DAYS,
  maxDate = lastDays(1).date_to
): string | undefined {
  for (const value of [range.date_from, range.date_to]) {
    const date = parseISO(value)
    if (
      !/^\d{4}-\d{2}-\d{2}$/.test(value) ||
      !isValid(date) ||
      toISODate(date) !== value
    )
      return 'Выберите корректные даты'
  }
  if (range.date_from > range.date_to) return 'Начало периода позже окончания'
  if (range.date_from < HISTORY_START) return 'История доступна с 29.01.2024'
  if (range.date_to > maxDate) return 'Выберите завершённые дни'
  if (
    differenceInCalendarDays(
      parseISO(range.date_to),
      parseISO(range.date_from)
    ) >= maxDays
  )
    return `Выберите не больше ${maxDays} дней`
}

/** Быстрые итоги WB доступны только для периода, заканчивающегося вчера. */
export function supportsFunnelSummary(range: DateRange) {
  return range.date_to === lastDays(1).date_to && !rangeError(range, 28)
}
