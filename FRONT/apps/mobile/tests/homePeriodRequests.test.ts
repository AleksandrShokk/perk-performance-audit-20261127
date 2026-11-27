import { beforeEach, expect, it, vi } from 'vitest'

import { useHomeOverview } from '@/features/overview/home/hooks/useHomeOverview'
import { DEFAULT_HOME_FILTERS } from '@/features/overview/home/model/overviewTypes'

const calls = vi.hoisted(() => ({
  finance: vi.fn(),
  funnel: vi.fn(),
  summary: vi.fn(),
  stock: vi.fn(),
  inventory: vi.fn(),
  summaryReady: vi.fn()
}))

vi.mock('@/features/auth/providers/AuthProvider', () => ({
  useAuth: () => ({ user: { id: 'user' }, status: 'signedIn' })
}))
vi.mock('@/features/workspace/providers/WorkspaceProvider', () => ({
  useWorkspace: () => ({
    workspace: { id: 'workspace' },
    store: { id: 'store' },
    stores: [{ id: 'store' }],
    allStores: false,
    supports: () => true,
    can: () => true,
    accessKey: 'full'
  })
}))
vi.mock('@/features/supplies/hooks/useSupplies', () => ({
  useReplenishment: () => ({
    data: undefined,
    refetch: calls.stock,
    isRefetching: false
  })
}))
vi.mock('@/features/inventory/hooks/useInventoryOverview', () => ({
  useInventoryOverview: () => ({ refetch: calls.inventory })
}))
vi.mock('@/lib/snapshot', () => ({
  fetchSnapshot: vi.fn(),
  refetchWhileStale: vi.fn()
}))
vi.mock('@/features/finance/hooks/useFinance', () => ({
  useFinance: () => ({ refetch: calls.finance })
}))
vi.mock('@/features/overview/funnel/hooks/useFunnel', () => ({
  useFunnel: () => ({ reports: [], refresh: calls.funnel })
}))
vi.mock('@/features/overview/funnel/hooks/useFunnelSummary', () => ({
  useFunnelSummary: (_range: unknown, ready: boolean) => {
    calls.summaryReady(ready)
    return { reports: [], refresh: calls.summary }
  }
}))

beforeEach(() => vi.clearAllMocks())

it('исторический диапазон не вызывает несовместимый summary даже при обновлении вручную', async () => {
  const overview = useHomeOverview({
    ...DEFAULT_HOME_FILTERS,
    period: { date_from: '2025-10-01', date_to: '2025-10-20' }
  })
  expect(calls.summaryReady).toHaveBeenCalledWith(false)
  await overview.refresh()
  expect(calls.summary).not.toHaveBeenCalled()
  expect(calls.funnel).toHaveBeenCalledOnce()
  expect(calls.finance).toHaveBeenCalledOnce()
  expect(calls.stock).toHaveBeenCalledOnce()
  expect(calls.inventory).toHaveBeenCalledOnce()
})

it('обычный свежий период продолжает обновлять быстрые итоги', async () => {
  const overview = useHomeOverview(DEFAULT_HOME_FILTERS)
  expect(calls.summaryReady).toHaveBeenCalledWith(true)
  await overview.refresh()
  expect(calls.summary).toHaveBeenCalledOnce()
})
