import { format, parseISO } from 'date-fns'
import { ru } from 'date-fns/locale'

import { formatShortDate } from '@/lib/format'

import type { ChartGrouping, ChartPoint } from './chartPoints'

/** «24 окт.», «20–26 окт.», «окт.»; полная форма месяца — «октябрь» или «24–31 окт.». */
export function pointLabel(
  point: ChartPoint,
  grouping: ChartGrouping,
  axis = false
) {
  const start = parseISO(point.day)
  const end = parseISO(point.end)
  if (
    grouping === 'day' ||
    point.day === point.end ||
    (axis && grouping === 'week')
  )
    return formatShortDate(point.day)
  if (grouping === 'month' && axis) return format(start, 'LLL', { locale: ru })
  if (grouping === 'month' && point.day.endsWith('-01')) {
    const lastDay = format(end, 'd')
    const monthEnd = format(
      new Date(start.getFullYear(), start.getMonth() + 1, 0),
      'd'
    )
    if (lastDay === monthEnd) return format(start, 'LLLL', { locale: ru })
  }
  return start.getMonth() === end.getMonth()
    ? `${format(start, 'd')}–${formatShortDate(point.end)}`
    : `${formatShortDate(point.day)} – ${formatShortDate(point.end)}`
}
