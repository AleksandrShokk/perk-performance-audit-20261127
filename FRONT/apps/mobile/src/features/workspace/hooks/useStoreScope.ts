import { useAuth } from '@/features/auth/providers/AuthProvider'
import type { Permission } from '@/features/team/model/permissions'

import type { StoreFeature } from '../model/storeFeatures'
import { useWorkspace } from '../providers/WorkspaceProvider'

/** One access boundary and cache namespace for store-scoped requests. */
export function useStoreScope(
  permission: Permission,
  feature: StoreFeature = 'inventory'
) {
  const { user, status } = useAuth()
  const { workspace, store, allStores, accessKey, can, supports } =
    useWorkspace()
  return {
    key: ['user', user?.id, workspace?.id, store?.id ?? 'all', accessKey],
    workspaceId: workspace?.id,
    storeId: allStores ? undefined : store?.id,
    enabled:
      status === 'signedIn' &&
      !!workspace &&
      (allStores || !!store) &&
      can(permission) &&
      supports(feature)
  }
}
