import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useForm } from 'react-hook-form'

import { type ReplaceOzonKeyValues, replaceOzonKeySchema } from '@app/schemas'

import {
  storeCheckConnection,
  storeConnectionStatus,
  storeReplaceOzonCredential
} from '@app/api'

import { useAuth } from '@/features/auth/providers/AuthProvider'
import { useStepUp } from '@/features/auth/stepUp/StepUpProvider'
import { useWorkspace } from '@/features/workspace/providers/WorkspaceProvider'

export function useOzonConnection(workspaceId: string, storeId: string) {
  const { user } = useAuth()
  const { refetch } = useWorkspace()
  const client = useQueryClient()
  const withStepUp = useStepUp()
  const [notice, setNotice] = useState<'saved' | 'checked' | null>(null)
  const key = ['user', user?.id, workspaceId, 'store-connection', storeId]
  const form = useForm<ReplaceOzonKeyValues>({
    resolver: zodResolver(replaceOzonKeySchema),
    defaultValues: { api_key: '' }
  })
  const connection = useQuery({
    queryKey: key,
    queryFn: ({ signal }) =>
      storeConnectionStatus(workspaceId, storeId, { signal }),
    meta: { persist: false }
  })
  const refresh = () =>
    Promise.allSettled([client.invalidateQueries({ queryKey: key }), refetch()])
  const check = useMutation({
    mutationFn: () =>
      withStepUp(() => storeCheckConnection(workspaceId, storeId)),
    onMutate: () => setNotice(null),
    onSuccess: () => setNotice('checked'),
    onSettled: refresh,
    retry: false,
    gcTime: 0
  })
  const save = useMutation({
    mutationFn: ({ api_key }: ReplaceOzonKeyValues) => {
      const clientId = connection.data?.client_id
      if (!clientId) throw new Error('Подключение ещё не загружено')
      return withStepUp(() =>
        storeReplaceOzonCredential(workspaceId, storeId, {
          client_id: clientId,
          api_key
        })
      )
    },
    onMutate: () => setNotice(null),
    onSuccess: async () => {
      setNotice('saved')
      form.reset()
      await refresh()
    },
    retry: false,
    gcTime: 0
  })
  const submit = form.handleSubmit(values => save.mutate(values))
  return {
    form,
    connection,
    check: () => check.mutate(),
    submit: () => void submit(),
    saved: notice === 'saved' && !form.formState.isDirty,
    checked: notice === 'checked',
    pending: save.isPending || check.isPending,
    checking: check.isPending,
    saving: save.isPending,
    error: save.error ?? check.error
  }
}
