import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { catalogSyncRefresh, catalogSyncStatus } from '@app/api'

import { useAuth } from '@/features/auth/providers/AuthProvider'

export function useCatalogSync(workspaceId: string, storeId: string) {
  const { user } = useAuth()
  const client = useQueryClient()
  const key = ['user', user?.id, workspaceId, storeId, 'catalog-sync']
  const status = useQuery({
    queryKey: key,
    queryFn: ({ signal }) =>
      catalogSyncStatus(workspaceId, storeId, { signal }),
    refetchInterval: query =>
      ['pending', 'queued', 'running'].includes(query.state.data?.status ?? '')
        ? 3000
        : 60000,
    meta: { persist: false }
  })
  const refresh = useMutation({
    mutationFn: () => catalogSyncRefresh(workspaceId, storeId),
    onSuccess: data => {
      client.setQueryData(key, data)
      void client.invalidateQueries({
        queryKey: ['user', user?.id, workspaceId]
      })
    },
    retry: false
  })
  return { status, refresh }
}
