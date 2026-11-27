import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { router } from 'expo-router'
import { useForm } from 'react-hook-form'

import { type ConnectOzonValues, connectOzonSchema } from '@app/schemas'

import { storeConnectOzon } from '@app/api'

import { useStepUp } from '@/features/auth/stepUp/StepUpProvider'
import { useWorkspace } from '@/features/workspace/providers/WorkspaceProvider'

/** Verification creates a connection, not a WB sync schedule. */
export function useConnectOzon() {
  const { workspace } = useWorkspace()
  const client = useQueryClient()
  const withStepUp = useStepUp()
  const form = useForm<ConnectOzonValues>({
    resolver: zodResolver(connectOzonSchema),
    defaultValues: { name: '', client_id: '', api_key: '' }
  })
  const connection = useMutation({
    mutationFn: (values: ConnectOzonValues) => {
      if (!workspace) throw new Error('Кабинет ещё не загружен')
      return withStepUp(() => storeConnectOzon(workspace.id, values))
    },
    onSuccess: async store => {
      form.reset()
      await Promise.allSettled([
        client.invalidateQueries({
          predicate: query => query.queryKey.includes('stores')
        })
      ])
      router.replace({
        pathname: '/stores/[storeId]',
        params: { storeId: store.id }
      })
    },
    retry: false,
    gcTime: 0
  })
  const submit = form.handleSubmit(values => connection.mutate(values))
  return {
    form,
    submit: () => void submit(),
    pending: connection.isPending,
    error: connection.error
  }
}
