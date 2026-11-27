'use client'

import { resolvePeriod } from '@app/analytics/periods'
import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useRef } from 'react'

import { useAuth } from '@/features/auth/auth-provider'
import { readPeriod } from '@/features/finance/hooks/use-finance'
import { readSupplyParameters } from '@/features/supplies/model/parameters'
import { useWorkspace } from '@/features/workspace/workspace-provider'

import { usePreference } from '@/lib/preferences'
import {
  financeQuery,
  productQuery,
  stockQuery,
  supplyQuery
} from '@/lib/report-queries'

/** Warm the same private queries that each screen uses. Reports stay in memory. */
export function usePrefetchSections(pathname: string) {
  const client = useQueryClient()
  const scope = useWorkspace()
  const { user } = useAuth()
  const userId = user?.id
  const workspaceId = scope.workspace?.id
  const storeId = scope.store?.id
  const accessKey = scope.accessKey
  const ready = scope.ready && !!userId && !!workspaceId
  const canStock = scope.can('inventory.read')
  const canProfit = scope.can('profit.read')
  const canFinance = scope.can('finance.read')
  const features = [...new Set(scope.selected.flatMap(s => s.features))]
    .sort()
    .join(',')
  const crossMarketplace =
    !storeId && new Set(scope.selected.map(s => s.marketplace)).size > 1
  const [financePeriod] = usePreference(`perk.web.finance.period.${userId}`)
  const [coverage] = usePreference(
    `perk.web.coverage-channel.${userId}.${workspaceId}`
  )
  const [parameters] = usePreference(
    `perk.web.supplies.parameters.${userId}.${workspaceId}`
  )
  const [combined] = usePreference(`perk.web.products.combined.${userId}`)
  const [variants] = usePreference(`perk.web.products.variants.${userId}`)
  const channel = coverage === 'fbs' || coverage === 'all' ? coverage : 'fbo'
  const source = useMemo(
    () => ({ userId, workspaceId, storeId, accessKey, canStock }),
    [userId, workspaceId, storeId, accessKey, canStock]
  )
  const activeScope = useRef('')
  const scopeKey = JSON.stringify([
    userId,
    workspaceId,
    storeId,
    accessKey,
    ready
  ])
  useEffect(() => {
    activeScope.current = scopeKey
    return () => {
      activeScope.current = ''
    }
  }, [scopeKey])
  const warm = useCallback(
    async (href: string) => {
      if (!ready || activeScope.current !== scopeKey) return
      const supports = (name: string) => features.split(',').includes(name)
      // Sequential requests avoid competing with the active screen for API workers.
      if (href === '/finance' && canFinance && supports('finance')) {
        await client.prefetchQuery(
          financeQuery(source, resolvePeriod(readPeriod(financePeriod)))
        )
      } else if (href === '/inventory' && canStock && supports('inventory')) {
        await client.prefetchQuery(stockQuery(source, channel))
        if (activeScope.current !== scopeKey) return
        await client.prefetchQuery(
          stockQuery(source, channel, { search: '', inStock: true, page: 0 })
        )
      } else if (
        href === '/products' &&
        (canStock || canProfit) &&
        supports('catalog')
      ) {
        await client.prefetchQuery(
          productQuery(source, {
            search: '',
            inStock: false,
            missingCost: false,
            page: 0,
            pageSize: 25,
            combined:
              crossMarketplace && combined !== 'false' && variants !== 'true'
          })
        )
      } else if (href === '/supplies' && canStock && supports('supplies')) {
        const value = readSupplyParameters(parameters)
        await client.prefetchQuery(supplyQuery(source, value))
        if (activeScope.current !== scopeKey) return
        await client.prefetchQuery(
          supplyQuery(source, value, { storeId, urgent: false, page: 0 })
        )
      }
    },
    [
      scopeKey,
      ready,
      features,
      canFinance,
      canStock,
      canProfit,
      client,
      source,
      financePeriod,
      channel,
      crossMarketplace,
      combined,
      variants,
      parameters,
      storeId
    ]
  )
  useEffect(() => {
    let cancelled = false
    const routes = ['/products', '/finance', '/inventory', '/supplies'].filter(
      href => href !== pathname
    )
    let timer: ReturnType<typeof setTimeout>
    async function next() {
      if (cancelled || !ready) return
      const firstLoad =
        client.isFetching({ predicate: q => q.state.status === 'pending' }) > 0
      if (firstLoad) {
        timer = setTimeout(() => void next(), 1000)
        return
      }
      const href = routes.shift()
      if (!href) return
      await warm(href)
      if (!cancelled) timer = setTimeout(() => void next(), 300)
    }
    timer = setTimeout(() => void next(), 1000)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [client, pathname, ready, warm])
  return warm
}
