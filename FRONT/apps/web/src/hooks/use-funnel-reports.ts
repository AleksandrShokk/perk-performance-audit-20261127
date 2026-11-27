'use client'

import { type DateRange, HISTORY_START } from '@app/analytics/dates'
import { supportsFunnelSummary } from '@app/analytics/periods'
import { progressInterval, reportInterval } from '@app/analytics/polling'
import { previousPeriod } from '@app/analytics/sales'
import { useQueries, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef } from 'react'

import {
  insightsFunnel,
  insightsFunnelAvailability,
  insightsFunnelProgress,
  insightsFunnelSummary
} from '@app/api'

import { useAuth } from '@/features/auth/auth-provider'
import { useWorkspace } from '@/features/workspace/workspace-provider'

import { availableFunnelPeriod, wbHistoryNotice } from './funnel-period'

type PollQuery = {
  state: {
    data?: {
      is_loading?: boolean
      error_code?: string | null
      freshness: { stale: boolean }
    }
  }
}
function poll(query: PollQuery) {
  return reportInterval(query.state.data)
}
/** One cache for the home chart and analytics. Marketplace imports stay on the server. */
export function useFunnelReports(
  requestedRange: DateRange,
  comparison: boolean,
  priceBasis: 'customer' | 'seller' = 'customer'
) {
  const scope = useWorkspace()
  const { user } = useAuth()
  const stores = useMemo(
    () => scope.selected.filter(store => store.features.includes('analytics')),
    [scope.selected]
  )
  const client = useQueryClient()
  const pollingStarted = useRef(0)
  useEffect(() => {
    pollingStarted.current = Date.now()
  }, [requestedRange.date_from, requestedRange.date_to, scope.accessKey])
  const revisions = useRef(new Map<string, string>())
  const enabled =
    scope.ready && !!scope.workspace && scope.can('analytics.read')
  const key = useMemo(
    () => ['user', user?.id, scope.workspace?.id, scope.accessKey],
    [user?.id, scope.workspace?.id, scope.accessKey]
  )
  const wbStores = stores.filter(store => store.marketplace === 'wildberries')
  const availability = useQueries({
    queries: wbStores.map(store => ({
      queryKey: [...key, 'funnel-availability', store.id],
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        insightsFunnelAvailability(scope.workspace!.id, store.id, { signal }),
      enabled,
      staleTime: 60000,
      refetchInterval: 60000
    }))
  })
  const singleWB = scope.store?.marketplace === 'wildberries'
  const minDate = singleWB ? availability[0]?.data?.date_from : undefined
  const periodPending = !!singleWB && !minDate
  const canLoad = enabled && (!singleWB || !!minDate)
  const range = availableFunnelPeriod(requestedRange, minDate)
  const historyNotice = !scope.store
    ? wbHistoryNotice(
        range,
        availability.map(query => query.data)
      )
    : undefined
  const params = useMemo(
    () => ({ ...range, price_basis: priceBasis }),
    [range, priceBasis]
  )
  const before = previousPeriod(range)
  const summarySupported = supportsFunnelSummary(range)
  const current = useQueries({
    queries: stores.map(store => ({
      queryKey: [...key, 'funnel', store.id, params],
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        insightsFunnel(scope.workspace!.id, store.id, params, { signal }),
      enabled: canLoad,
      staleTime: 30000,
      refetchInterval: (query: PollQuery) =>
        store.marketplace === 'wildberries' &&
        query.state.data?.is_loading &&
        !query.state.data.freshness.stale
          ? false
          : poll(query)
    }))
  })
  const progress = useQueries({
    queries: stores.map((store, index) => ({
      queryKey: [...key, 'funnel-progress', store.id, range],
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        insightsFunnelProgress(scope.workspace!.id, store.id, range, {
          signal
        }),
      enabled:
        canLoad &&
        store.marketplace === 'wildberries' &&
        !!current[index]?.data?.is_loading,
      refetchInterval: () =>
        progressInterval(pollingStarted.current, stores.length),
      gcTime: 0
    }))
  })
  useEffect(() => {
    progress.forEach((query, index) => {
      if (!query.data) return
      const queryKey = current[index] && [
        ...key,
        'funnel',
        stores[index]!.id,
        params
      ]
      if (!queryKey) return
      const marker = JSON.stringify(queryKey)
      if (revisions.current.get(marker) === query.data.revision) return
      revisions.current.set(marker, query.data.revision)
      void client.invalidateQueries({ queryKey, exact: true })
    })
  }, [progress, current, key, stores, params, client])
  const previous = useQueries({
    queries: stores.map(store => ({
      queryKey: [
        ...key,
        'funnel',
        store.id,
        { ...before, price_basis: priceBasis }
      ],
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        insightsFunnel(
          scope.workspace!.id,
          store.id,
          {
            ...before,
            price_basis: priceBasis,
            date_from:
              before.date_from < HISTORY_START
                ? HISTORY_START
                : before.date_from
          },
          { signal }
        ),
      enabled: canLoad && before.date_to >= HISTORY_START && comparison,
      staleTime: 30000,
      refetchInterval: (query: PollQuery) =>
        current.some(query => query.data?.is_loading) &&
        !query.state.data?.freshness.stale
          ? false
          : poll(query)
    }))
  })
  const summaries = useQueries({
    queries: stores.map(store => ({
      queryKey: [...key, 'funnel-summary', store.id, params],
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        insightsFunnelSummary(scope.workspace!.id, store.id, params, {
          signal
        }),
      enabled: canLoad && summarySupported,
      staleTime: 30000,
      refetchInterval: current.some(query => query.data?.is_loading)
        ? false
        : poll
    }))
  })
  return {
    range,
    minDate,
    periodPending,
    historyNotice,
    availability,
    stores,
    current,
    previous,
    summaries,
    summarySupported,
    progress
  }
}
