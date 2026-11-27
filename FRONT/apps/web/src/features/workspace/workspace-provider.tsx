'use client'

import {
  type Permission,
  isAdminRole,
  permissionsFor
} from '@app/analytics/permissions'
import { useQuery } from '@tanstack/react-query'
import { type ReactNode, createContext, use, useState } from 'react'

import {
  type StoreResponse,
  type WorkspaceResponse,
  storesList,
  workspacesList
} from '@app/api'

import { useAuth } from '@/features/auth/auth-provider'

import { usePreference } from '@/lib/preferences'

type Workspace = {
  workspace?: WorkspaceResponse
  workspaces: WorkspaceResponse[]
  connections: StoreResponse[]
  stores: StoreResponse[]
  selected: StoreResponse[]
  store?: StoreResponse
  ready: boolean
  loading: boolean
  error: unknown
  importNotice?: string
  showImportNotice: (name: string) => void
  dismissImportNotice: () => void
  accessKey: string
  can: (permission: Permission) => boolean
  admin: boolean
  selectStore: (id: string) => void
  selectWorkspace: (id: string) => void
  refresh: () => Promise<unknown>
}
const Context = createContext<Workspace | null>(null)
export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const { user, status } = useAuth()
  const [notice, setNotice] = useState<{
    userId?: string
    workspaceId?: string
    name: string
  } | null>(null)
  const enabled = status === 'authenticated' && !!user?.session_mfa_verified
  const [workspaceId, setWorkspaceId] = usePreference(
    `perk.web.workspace.${user?.id}`
  )
  const list = useQuery({
    queryKey: ['user', user?.id, 'workspaces'],
    queryFn: ({ signal }) => workspacesList({ signal }),
    enabled,
    staleTime: 30000,
    refetchInterval: 30000
  })
  const workspaces = enabled ? (list.data ?? []) : []
  const workspace =
    workspaces.find(row => row.id === workspaceId) ??
    workspaces.find(row => row.role === 'owner') ??
    workspaces[0]
  const permissions = permissionsFor(workspace)
  const accessKey = JSON.stringify([
    workspace?.id,
    workspace?.role,
    permissions,
    workspace?.store_ids
  ])
  const connections = useQuery({
    queryKey: ['user', user?.id, 'stores', accessKey],
    queryFn: ({ signal }) => storesList(workspace!.id, { signal }),
    enabled: enabled && !!workspace,
    staleTime: 30000,
    refetchInterval: 30000
  })
  const stores =
    workspace && enabled
      ? (connections.data ?? []).filter(
          row => row.features?.includes('catalog') || row.reports_available
        )
      : []
  const [storeId, setStoreId] = usePreference(
    `perk.web.store.${user?.id}.${workspace?.id}`
  )
  const store =
    storeId === 'all' && stores.length > 1
      ? undefined
      : (stores.find(row => row.id === storeId) ?? stores[0])
  const selected = store ? [store] : stores
  const error = list.error ?? connections.error
  return (
    <Context
      value={{
        workspace,
        workspaces,
        connections: enabled && workspace ? (connections.data ?? []) : [],
        stores,
        selected,
        store,
        accessKey,
        importNotice:
          notice?.userId === user?.id && notice?.workspaceId === workspace?.id
            ? notice?.name
            : undefined,
        showImportNotice: name =>
          setNotice({ userId: user?.id, workspaceId: workspace?.id, name }),
        dismissImportNotice: () => setNotice(null),
        admin: isAdminRole(workspace?.role),
        loading:
          enabled && (list.isPending || (!!workspace && connections.isPending)),
        ready: enabled && !!list.data && (!workspace || !!connections.data),
        error,
        can: permission => permissions.includes(permission),
        selectStore: setStoreId,
        selectWorkspace: setWorkspaceId,
        refresh: () => Promise.all([list.refetch(), connections.refetch()])
      }}
    >
      {children}
    </Context>
  )
}
export function useWorkspace() {
  const value = use(Context)
  if (!value) throw new Error('WorkspaceProvider отсутствует')
  return value
}
