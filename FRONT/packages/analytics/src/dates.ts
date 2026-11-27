import { addDays, format, parseISO, subDays } from 'date-fns'

/** Самая ранняя дата, за которую WB отдаёт финансовые отчёты. */
export const HISTORY_START = '2024-01-29'
const MOSCOW_OFFSET_MS = 3 * 60 * 60 * 1000

export type DateRange = { date_from: string; date_to: string }

/** Сегодняшняя дата по Москве в формате YYYY-MM-DD: отчёты WB считаются по московским суткам. */
export function moscowToday(): string {
  return new Date(Date.now() + MOSCOW_OFFSET_MS).toISOString().slice(0, 10)
}

export function toISODate(date: Date) {
  return format(date, 'yyyy-MM-dd')
}

/**
 * Последние `days` завершённых дней по Москве (без сегодняшнего).
 * Совпадает с периодами, которые сервер готовит заранее.
 */
export function lastDays(days: number): DateRange {
  const end = subDays(parseISO(moscowToday()), 1)
  const start = toISODate(subDays(end, days - 1))
  return {
    date_from: start < HISTORY_START ? HISTORY_START : start,
    date_to: toISODate(end)
  }
}

/** Все дни периода включительно. */
export function eachDay({ date_from, date_to }: DateRange): string[] {
  const days: string[] = []
  for (
    let day = parseISO(date_from);
    toISODate(day) <= date_to;
    day = addDays(day, 1)
  )
    days.push(toISODate(day))
  return days
}
