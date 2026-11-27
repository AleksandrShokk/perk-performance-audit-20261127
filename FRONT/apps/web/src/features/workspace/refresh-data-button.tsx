'use client'

import { RefreshCw } from 'lucide-react'
import { useEffect } from 'react'

import { Button } from '@/components/ui/button'

import { useProtectedAction } from '@/hooks/use-protected-action'

import { refreshSelectedStores } from './refresh-data'
import { useWorkspace } from './workspace-provider'

export function RefreshDataButton({
  onRefresh,
  onError,
  disabled = false
}: {
  onRefresh: () => Promise<unknown>
  onError: (error: unknown) => void
  disabled?: boolean
}) {
  const scope = useWorkspace()
  const action = useProtectedAction(
    async signal => {
      if (scope.admin && scope.workspace)
        await refreshSelectedStores(scope.workspace.id, scope.selected, signal)
    },
    async () => {
      await Promise.all([scope.refresh(), onRefresh()])
    },
    { refresh: false }
  )
  const { reset, isSuccess, error } = action
  useEffect(() => onError(error), [error, onError])
  useEffect(() => {
    if (!isSuccess) return
    const timer = setTimeout(reset, 30_000)
    return () => clearTimeout(timer)
  }, [isSuccess, reset])

  return (
    <Button
      variant='ghost'
      className='refresh-button'
      aria-label='Обновить данные'
      aria-busy={action.isPending}
      disabled={
        disabled ||
        scope.loading ||
        !scope.selected.length ||
        action.isPending ||
        isSuccess
      }
      onClick={() => action.mutate()}
    >
      <RefreshCw
        size={15}
        className={action.isPending ? 'animate-spin' : ''}
      />
      <span aria-live='polite'>
        {action.isPending
          ? 'Обновляется…'
          : isSuccess
            ? scope.admin
              ? 'Запущено'
              : 'Обновлено'
            : 'Обновить данные'}
      </span>
    </Button>
  )
}
