import { useQuery } from '@tanstack/react-query'

import { type BusinessReportParams, businessReport } from '@app/api'

import { useAuth } from '@/features/auth/providers/AuthProvider'
import {
  type ReportPeriod,
  resolvePeriod
} from '@/features/periods/model/periodRange'
import { reportPermission } from '@/features/team/model/permissions'
import { useWorkspace } from '@/features/workspace/providers/WorkspaceProvider'

export function businessQuery(
  userId: string,
  workspaceId: string,
  storeId: string | undefined,
  period: ReportPeriod,
  topic: BusinessReportParams['topic'] = 'overview',
  accessKey = ''
) {
  const range = resolvePeriod(period)
  // Финансовые страницы используют ту же сводку, что блок финансов главной.
  const section = topic === 'sales' || topic === 'profit' ? 'overview' : topic
  return {
    queryKey: [
      'user',
      userId,
      workspaceId,
      storeId ?? 'all',
      'business-v6',
      accessKey,
      range,
      section
    ],
    queryFn: ({ signal }: { signal: AbortSignal }) =>
      businessReport(
        workspaceId,
        { ...range, store_id: storeId, topic: section },
        { signal }
      ),
    meta: { persist: true }
  }
}

/** Один запрос для главной и подробностей: готовые отчёты со всех видимых магазинов. */
export function useBusiness(
  period: ReportPeriod,
  topic: BusinessReportParams['topic'] = 'overview'
) {
  const { user, status } = useAuth()
  const { workspace, store, stores, allStores, can, accessKey, supports } =
    useWorkspace()
  return useQuery({
    ...businessQuery(
      user?.id ?? '',
      workspace?.id ?? '',
      allStores ? undefined : (store?.id ?? '__pending__'),
      period,
      topic,
      accessKey
    ),
    enabled:
      status === 'signedIn' &&
      supports('finance_details') &&
      !!workspace &&
      stores.length > 0 &&
      (topic === 'overview' || can(reportPermission(topic ?? 'overview'))),
    refetchInterval: query => {
      const value = query.state.data
      // Неполная история может быть за пределами хранения WB: не опрашивать её
      // каждые 5 секунд бесконечно. Частый опрос — только во время импорта финансов.
      return value &&
        value.stores.some(
          store =>
            store.finance.status === 'preparing' || store.finance.is_partial
        )
        ? 5000
        : 60000
    }
  })
}
