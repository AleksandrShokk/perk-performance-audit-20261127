import { homePeriod } from '@app/analytics/sales'
import type { HomePeriod } from '@app/analytics/sales-types'

import { ReportPeriodControl } from '@/components/report-period-control'

export function PeriodControl({
  value,
  onChange,
  minDate,
  disabled
}: {
  value: HomePeriod
  onChange: (period: HomePeriod) => void
  minDate?: string
  disabled?: boolean
}) {
  return (
    <ReportPeriodControl
      value={value === 'week' ? homePeriod(value) : value}
      onChange={onChange}
      options={[7, 14, 28] as const}
      maxDays={1100}
      minDate={minDate}
      disabled={disabled}
    />
  )
}
