import { reportInterval } from '@app/analytics/polling'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { financeOverview } from '@app/api'

import { useAuth } from '@/features/auth/providers/AuthProvider'
import {
  type ReportPeriod,
  resolvePeriod
} from '@/features/periods/model/periodRange'
import { useWorkspace } from '@/features/workspace/providers/WorkspaceProvider'

export type FinanceDays = 7 | 30 | 90

export function useFinance(period: ReportPeriod) {
  const { user, status } = useAuth()
  const { workspace, store, stores, allStores, can, accessKey, supports } =
    useWorkspace()
  const range = resolvePeriod(period)
  return useQuery({
    queryKey: [
      'user',
      user?.id,
      workspace?.id,
      store?.id ?? 'all',
      'finance-overview-v6',
      accessKey,
      range
    ],
    queryFn: ({ signal }) =>
      financeOverview(
        workspace!.id,
        {
          ...range,
          store_id: allStores ? undefined : store?.id
        },
        { signal }
      ),
    enabled:
      status === 'signedIn' &&
      supports('finance') &&
      can('finance.read') &&
      !!workspace &&
      stores.length > 0 &&
      (allStores || !!store),
    meta: { persist: true },
    refetchOnMount: 'always',
    refetchInterval: query => reportInterval(query.state.data)
  })
}

/** Расходы, цены и налоги обновляют также финансовый блок на главной. */
export function useRefreshFinance() {
  const client = useQueryClient()
  const { user } = useAuth()
  const { workspace } = useWorkspace()
  return () =>
    client.invalidateQueries({ queryKey: ['user', user?.id, workspace?.id] })
}
