import { format, getDay, parseISO } from 'date-fns'
import { expect, it } from 'vitest'

import { calendarDays } from '@/features/periods/model/calendarDays'

it.each(['2026-02-01', '2026-08-01', '2026-09-01', '2024-02-01', '2025-12-01'])(
  'календарь %s занимает шесть недель, включает все дни месяца и начинается с понедельника',
  month => {
    const days = calendarDays(parseISO(month))
    expect(days).toHaveLength(42)
    expect(getDay(days[0]!)).toBe(1)
    expect(getDay(days[41]!)).toBe(0)
    const current = days.filter(
      day => format(day, 'yyyy-MM') === month.slice(0, 7)
    )
    expect(format(current[0]!, 'dd')).toBe('01')
    expect(format(current.at(-1)!, 'yyyy-MM-dd')).toBe(
      format(
        new Date(Number(month.slice(0, 4)), Number(month.slice(5, 7)), 0),
        'yyyy-MM-dd'
      )
    )
  }
)
