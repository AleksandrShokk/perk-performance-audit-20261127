'use client'
import { useAuth } from '@/features/auth/auth-provider'
import { useWorkspace } from '@/features/workspace/workspace-provider'

import { usePreference } from '@/lib/preferences'

export function useCoverageChannel() {
  const { user } = useAuth(),
    scope = useWorkspace()
  const [saved, set] = usePreference(
    `perk.web.coverage-channel.${user?.id}.${scope.workspace?.id}`
  )
  const channel: 'fbo' | 'fbs' | 'all' =
    saved === 'fbs' || saved === 'all' ? saved : 'fbo'
  return [channel, set] as const
}
