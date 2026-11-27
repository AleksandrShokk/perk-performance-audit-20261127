'use client'

import { useMutation } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'

import { StepUpCancelled, useStepUp } from '@/features/auth/step-up-provider'
import { useWorkspace } from '@/features/workspace/workspace-provider'

import { useRefreshWorkspace } from '@/hooks/use-refresh-workspace'

import { errorMessage } from '@/lib/errors'
import { browserSession } from '@/lib/http'

/** Secrets stay in the form, not mutation variables, keys or stored Axios configs. */
export function useProtectedAction<T>(
  operation: (signal: AbortSignal) => Promise<T>,
  onSaved?: (result: T) => void | Promise<void>,
  options: { refresh?: boolean } = {}
) {
  const stepUp = useStepUp(),
    scope = useWorkspace(),
    refresh = useRefreshWorkspace()
  const controller = useRef<AbortController | null>(null)
  const epoch = useRef(browserSession.epoch)
  useEffect(() => {
    const current = new AbortController()
    controller.current = current
    return () => current.abort()
  }, [])
  const action = useMutation({
    mutationFn: async () => {
      const signal = controller.current?.signal
      if (!signal || signal.aborted) throw new StepUpCancelled()
      try {
        return await stepUp(() => {
          if (signal.aborted) throw new StepUpCancelled()
          return operation(signal)
        }, signal)
      } catch (error) {
        throw signal.aborted || error instanceof StepUpCancelled
          ? new StepUpCancelled()
          : new Error(errorMessage(error))
      }
    },
    onSuccess: async result => {
      if (!controller.current?.signal.aborted) await onSaved?.(result)
    },
    onSettled: () => {
      if (options.refresh !== false && epoch.current === browserSession.epoch)
        void Promise.allSettled([scope.refresh(), refresh()])
    },
    retry: false,
    gcTime: 0
  })
  return {
    ...action,
    error: action.error instanceof StepUpCancelled ? null : action.error
  }
}
