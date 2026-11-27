import { beforeEach, expect, it, vi } from 'vitest'

import { useStoreScope } from '@/features/workspace/hooks/useStoreScope'

const state = vi.hoisted(() => ({
  signedIn: true,
  userId: 'user-1',
  workspaceId: 'workspace-1' as string | undefined,
  storeId: 'store-1' as string | undefined,
  allStores: false,
  allowed: true,
  accessKey: 'owner'
}))

vi.mock('@/features/auth/providers/AuthProvider', () => ({
  useAuth: () => ({
    user: { id: state.userId },
    status: state.signedIn ? 'signedIn' : 'signedOut'
  })
}))
vi.mock('@/features/workspace/providers/WorkspaceProvider', () => ({
  useWorkspace: () => ({
    workspace: state.workspaceId ? { id: state.workspaceId } : undefined,
    store: state.storeId ? { id: state.storeId } : undefined,
    allStores: state.allStores,
    accessKey: state.accessKey,
    supports: () => state.allowed,
    can: () => state.allowed
  })
}))

beforeEach(() => {
  Object.assign(state, {
    signedIn: true,
    userId: 'user-1',
    workspaceId: 'workspace-1',
    storeId: 'store-1',
    allStores: false,
    allowed: true,
    accessKey: 'owner'
  })
})

it.each([
  { signedIn: false },
  { workspaceId: undefined },
  { storeId: undefined },
  { allowed: false }
])('does not send store requests before access is ready: %j', patch => {
  Object.assign(state, patch)
  expect(useStoreScope('inventory.read').enabled).toBe(false)
})

it('supports a selected store and all visible stores', () => {
  expect(useStoreScope('inventory.read')).toMatchObject({
    enabled: true,
    storeId: 'store-1'
  })
  Object.assign(state, { allStores: true, storeId: undefined })
  expect(useStoreScope('inventory.read')).toMatchObject({
    enabled: true,
    storeId: undefined
  })
})

it.each(['userId', 'workspaceId', 'storeId', 'accessKey'] as const)(
  'keeps cached reports separate when %s changes',
  field => {
    const previous = useStoreScope('inventory.read').key
    state[field] = 'changed'
    expect(useStoreScope('inventory.read').key).not.toEqual(previous)
  }
)
