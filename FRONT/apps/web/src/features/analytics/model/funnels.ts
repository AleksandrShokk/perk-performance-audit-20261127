import { summarizeFunnel } from '@app/analytics/funnel'

import type { FunnelReport, FunnelSummaryReport, StoreResponse } from '@app/api'

/** Native traffic definitions remain separate; counts from stores of one marketplace are additive. */
export function marketplaceFunnels(
  stores: Pick<StoreResponse, 'marketplace'>[],
  reports: (FunnelReport | undefined)[],
  summaries: (FunnelSummaryReport | undefined)[]
) {
  return (['wildberries', 'ozon'] as const).flatMap(marketplace => {
    const indexes = stores.flatMap((store, index) =>
      store.marketplace === marketplace ? [index] : []
    )
    return indexes.length
      ? [
          {
            marketplace,
            title: marketplace === 'ozon' ? 'Ozon' : 'WB',
            totals: summarizeFunnel(
              indexes.map(i => reports[i]),
              indexes.map(i => summaries[i])
            )
          }
        ]
      : []
  })
}
