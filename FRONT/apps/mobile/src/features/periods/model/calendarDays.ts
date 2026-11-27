import { addDays, eachDayOfInterval, startOfMonth, startOfWeek } from 'date-fns'

/** Шесть полных недель сохраняют высоту календаря при переключении месяца. */
export function calendarDays(month: Date) {
  const start = startOfWeek(startOfMonth(month), { weekStartsOn: 1 })
  return eachDayOfInterval({ start, end: addDays(start, 6 * 7 - 1) })
}
