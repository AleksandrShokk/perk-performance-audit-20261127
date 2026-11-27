'use client'

import {
  type ReportPeriod,
  rangeError,
  resolvePeriod
} from '@app/analytics/periods'
import { reportInterval } from '@app/analytics/polling'
import { useQuery } from '@tanstack/react-query'

import { useAuth } from '@/features/auth/auth-provider'
import { useWorkspace } from '@/features/workspace/workspace-provider'

import { usePreference } from '@/lib/preferences'
import { financeQuery } from '@/lib/report-queries'

export function readPeriod(value: string | null): ReportPeriod {
  try {
    const period = JSON.parse(value ?? '30')
    if ([7, 30, 90].includes(period)) return period
    if (period && typeof period === 'object' && !rangeError(period))
      return period
  } catch {
    /* Invalid old preferences fall back to 30 completed days. */
  }
  return 30
}
export function useFinance() {
  const scope = useWorkspace()
  const { user } = useAuth()
  const [saved, setSaved] = usePreference(`perk.web.finance.period.${user?.id}`)
  const period = readPeriod(saved)
  const range = resolvePeriod(period)
  const supported = scope.selected.some(store =>
    store.features.includes('finance')
  )
  const query = useQuery({
    ...financeQuery(
      {
        userId: user?.id,
        workspaceId: scope.workspace?.id,
        accessKey: scope.accessKey,
        storeId: scope.store?.id,
        canStock: scope.can('inventory.read')
      },
      range
    ),
    enabled:
      scope.ready &&
      !!scope.workspace &&
      supported &&
      scope.can('finance.read'),
    refetchInterval: query => reportInterval(query.state.data)
  })
  return {
    ...query,
    period,
    range,
    supported,
    setPeriod: (value: ReportPeriod) => setSaved(JSON.stringify(value))
  }
}
export { useRefreshWorkspace as useRefreshFinance } from '@/hooks/use-refresh-workspace'
