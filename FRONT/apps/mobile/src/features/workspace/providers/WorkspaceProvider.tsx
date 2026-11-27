import AsyncStorage from '@react-native-async-storage/async-storage'
import { useQueryClient } from '@tanstack/react-query'
import {
  type ReactNode,
  createContext,
  use,
  useEffect,
  useRef,
  useState
} from 'react'

import {
  type StoreResponse,
  type WorkspaceResponse,
  useStoresList,
  useWorkspacesList
} from '@app/api'

import { useAuth } from '@/features/auth/providers/AuthProvider'
import { session } from '@/features/auth/session'
import {
  type Permission,
  isAdminRole,
  permissionsFor
} from '@/features/team/model/permissions'

import { reportingConnections } from '../model/reportingConnections'
import { type StoreFeature, selectionSupports } from '../model/storeFeatures'

type WorkspaceStatus = 'idle' | 'loading' | 'ready' | 'error'
type WorkspaceContextValue = {
  status: WorkspaceStatus
  workspace?: WorkspaceResponse
  workspaces: WorkspaceResponse[]
  stores: StoreResponse[]
  connections: StoreResponse[]
  store?: StoreResponse
  allStores: boolean
  /** Совместимость существующих кнопок управления магазином: owner и admin. */
  isOwner: boolean
  isAdmin: boolean
  accessKey: string
  supports: (feature: StoreFeature) => boolean
  can: (permission: Permission) => boolean
  selectStore: (storeId: string) => void
  selectWorkspace: (workspaceId: string) => Promise<void>
  refetch: () => Promise<unknown>
}
const WorkspaceContext = createContext<WorkspaceContextValue | null>(null)
const storeKey = (userId: string) => `perk.selected-store.${userId}`
const workspaceKey = (userId: string) => `perk.selected-workspace.${userId}`

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const { status: authStatus, user } = useAuth()
  const client = useQueryClient()
  const signedIn = authStatus === 'signedIn'
  const userId = user?.id
  const [selection, setSelection] = useState<{
    userId?: string
    workspaceId: string | null
    storeId: string | null
    ready: boolean
  }>({ workspaceId: null, storeId: null, ready: false })
  const writes = useRef(Promise.resolve())
  const selectionChanged = useRef(false)
  useEffect(() => {
    let active = true
    selectionChanged.current = false
    if (!userId) return
    void Promise.all([
      AsyncStorage.getItem(workspaceKey(userId)),
      AsyncStorage.getItem(storeKey(userId))
    ])
      .then(([workspaceId, storeId]) => {
        if (active && !selectionChanged.current)
          setSelection({ userId, workspaceId, storeId, ready: true })
      })
      .catch(() => {
        if (active && !selectionChanged.current)
          setSelection({
            userId,
            workspaceId: null,
            storeId: null,
            ready: true
          })
      })
    return () => {
      active = false
    }
  }, [userId])
  useEffect(
    () =>
      session.onEnd(() => {
        setSelection({ workspaceId: null, storeId: null, ready: false })
      }),
    []
  )

  const workspaces = useWorkspacesList({
    query: {
      queryKey: ['user', userId, 'workspaces'],
      enabled: signedIn,
      // Confirm permissions with the server before opening persisted reports.
      staleTime: 0,
      refetchInterval: 30000,
      meta: { persist: false }
    }
  })
  const ready = selection.userId === userId && selection.ready
  const list = signedIn ? (workspaces.data ?? []) : []
  const workspace = ready
    ? (list.find(item => item.id === selection.workspaceId) ??
      list.find(item => item.role === 'owner') ??
      list[0])
    : undefined
  const permissions = permissionsFor(workspace)
  const accessKey = JSON.stringify([
    workspace?.role,
    permissions,
    workspace?.store_ids
  ])
  const stores = useStoresList(workspace?.id ?? '', {
    query: {
      queryKey: ['user', userId, 'stores', workspace?.id, accessKey],
      enabled: signedIn && !!workspace,
      staleTime: 0,
      meta: { persist: false }
    }
  })
  const connections = signedIn && workspace ? (stores.data ?? []) : []
  const visibleStores = reportingConnections(connections)
  const allStores = selection.storeId === 'all' && visibleStores.length > 1
  const store = allStores
    ? undefined
    : (visibleStores.find(item => item.id === selection.storeId) ??
      visibleStores[0])
  function selectStore(storeId: string) {
    selectionChanged.current = true
    setSelection(current => ({ ...current, userId, storeId, ready: true }))
    if (userId)
      writes.current = writes.current
        .then(() => AsyncStorage.setItem(storeKey(userId), storeId))
        .catch(() => {})
  }
  async function selectWorkspace(workspaceId: string) {
    selectionChanged.current = true
    await client.cancelQueries({ queryKey: ['user', userId] })
    client.removeQueries({
      predicate: query =>
        query.queryKey[0] === 'user' &&
        query.queryKey[1] === userId &&
        query.queryKey[2] !== 'workspaces'
    })
    setSelection({ userId, workspaceId, storeId: null, ready: true })
    if (userId)
      writes.current = writes.current
        .then(async () => {
          await AsyncStorage.setItem(workspaceKey(userId), workspaceId)
          await AsyncStorage.removeItem(storeKey(userId))
        })
        .catch(() => {})
    await workspaces.refetch()
  }
  const status: WorkspaceStatus = !signedIn
    ? 'idle'
    : workspaces.isError || stores.isError
      ? 'error'
      : !ready || !workspaces.data || (workspace && !stores.data)
        ? 'loading'
        : 'ready'
  const isAdmin = isAdminRole(workspace?.role)
  return (
    <WorkspaceContext
      value={{
        status,
        workspace,
        workspaces: list,
        stores: visibleStores,
        connections,
        store,
        allStores,
        isOwner: isAdmin,
        isAdmin,
        can: permission => permissions.includes(permission),
        supports: feature =>
          selectionSupports(
            allStores ? visibleStores : store ? [store] : [],
            feature
          ),
        accessKey,
        selectStore,
        selectWorkspace,
        refetch: () =>
          Promise.all([
            workspaces.refetch(),
            ...(workspace ? [stores.refetch()] : [])
          ])
      }}
    >
      {children}
    </WorkspaceContext>
  )
}
export function useWorkspace() {
  const context = use(WorkspaceContext)
  if (!context) throw new Error('useWorkspace вызван вне WorkspaceProvider')
  return context
}
export function useCurrentStore() {
  const { workspace, store } = useWorkspace()
  if (!workspace || !store) throw new Error('Магазин ещё не подключён')
  return { workspaceId: workspace.id, storeId: store.id, store }
}
