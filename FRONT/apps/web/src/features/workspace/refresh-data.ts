import { type StoreResponse, storeRefreshData } from '@app/api'

/** Only selected, connected stores; no token or marketplace request enters browser code. */
export async function refreshSelectedStores(
  workspaceId: string,
  stores: StoreResponse[],
  signal: AbortSignal
) {
  const results = await Promise.allSettled(
    stores
      .filter(store => store.connection_status === 'connected')
      .map(store => storeRefreshData(workspaceId, store.id, { signal }))
  )
  const failed = results.find(result => result.status === 'rejected')
  if (failed?.status === 'rejected') throw failed.reason
}
