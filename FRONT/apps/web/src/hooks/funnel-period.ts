import type { DateRange } from '@app/analytics/dates'

export function availableFunnelPeriod(
  range: DateRange,
  first?: string
): DateRange {
  if (!first || range.date_from >= first) return range
  return {
    date_from: first,
    date_to: range.date_to < first ? first : range.date_to
  }
}

export function wbHistoryNotice(
  range: DateRange,
  bounds: (DateRange | undefined)[]
) {
  const limited = bounds.filter(
    bound => bound && range.date_from < bound.date_from
  )
  if (!limited.length) return undefined
  const dates = limited.map(bound => bound!.date_from).sort()
  const oneBoundary =
    limited.length === bounds.length && dates[0] === dates.at(-1)
  const label = oneBoundary ? 'WB учтён с' : 'Часть кабинетов WB учтена с'
  return `${label} ${dates.at(-1)!.split('-').reverse().join('.')}`
}
