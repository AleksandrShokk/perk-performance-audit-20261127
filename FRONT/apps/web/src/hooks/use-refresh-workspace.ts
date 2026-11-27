'use client'

import { useQueryClient } from '@tanstack/react-query'

import { useAuth } from '@/features/auth/auth-provider'
import { useWorkspace } from '@/features/workspace/workspace-provider'

export function useRefreshWorkspace() {
  const client = useQueryClient()
  const { user } = useAuth()
  const { workspace } = useWorkspace()
  return () =>
    client.invalidateQueries({ queryKey: ['user', user?.id, workspace?.id] })
}
