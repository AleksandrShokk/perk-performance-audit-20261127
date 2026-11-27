import type { DateRange } from './dates'

export type HomePeriod = 'week' | 7 | 14 | 28 | DateRange
export type ChartUnit = 'amount' | 'units'
export type ChartComparison = 'buyouts' | 'previous'

export type HomeFilters = {
  period: HomePeriod
  unit: ChartUnit
  comparison: ChartComparison
}

export const DEFAULT_HOME_FILTERS: HomeFilters = {
  period: 7,
  unit: 'amount',
  comparison: 'buyouts'
}

export const HOME_PERIODS = [
  { value: 'week', label: 'Неделя' },
  { value: 7, label: '7 дней' },
  { value: 14, label: '14 дней' },
  { value: 28, label: '28 дней' }
] as const

export type OrderBarPoint = {
  orderedPartial?: boolean
  buyoutsPartial?: boolean
  previousOrderedPartial?: boolean
  day: string
  previousDay: string
  ordered: string | null
  buyouts: string | null
  previousOrdered: string | null
  orderedUnits: string | null
  buyoutUnits: string | null
  partial: boolean
}

export type HomeSales = {
  orderedPartial?: boolean
  buyoutsPartial?: boolean
  knownDays: number
  points: OrderBarPoint[]
  ordered: string | null
  buyouts: string | null
  orderedChange: string | null
  buyoutsChange: string | null
  partial: boolean
  currency: string | null
  amountsUnavailable: boolean
}
