import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useForm } from 'react-hook-form'

import {
  type ReplaceStoreTokenValues,
  replaceStoreTokenSchema
} from '@app/schemas'

import { storeConnectionStatus, storeReplaceCredential } from '@app/api'

import { useAuth } from '@/features/auth/providers/AuthProvider'
import {
  StepUpCancelled,
  useStepUp
} from '@/features/auth/stepUp/StepUpProvider'
import { useWorkspace } from '@/features/workspace/providers/WorkspaceProvider'

/** Новый токен хранится только в форме; в запросах чтения и их кэше его нет. */
export function useReplaceStoreToken(workspaceId: string, storeId: string) {
  const { user } = useAuth()
  const { refetch } = useWorkspace()
  const client = useQueryClient()
  const withStepUp = useStepUp()
  const active = useRef(true)
  const [saved, setSaved] = useState(false)
  const key = ['user', user?.id, workspaceId, 'store-connection', storeId]
  const form = useForm<ReplaceStoreTokenValues>({
    resolver: zodResolver(replaceStoreTokenSchema),
    defaultValues: { token: '' }
  })
  useEffect(() => {
    active.current = true
    return () => {
      active.current = false
    }
  }, [])

  const connection = useQuery({
    queryKey: key,
    queryFn: ({ signal }) =>
      storeConnectionStatus(workspaceId, storeId, { signal }),
    meta: { persist: false }
  })
  const save = useMutation({
    mutationFn: async () => {
      const token = form.getValues('token').trim()
      return withStepUp(() => {
        if (!active.current) throw new StepUpCancelled()
        return storeReplaceCredential(workspaceId, storeId, { token })
      })
    },
    onMutate: () => setSaved(false),
    onSuccess: () => {
      form.reset()
      if (active.current) setSaved(true)
      void Promise.allSettled([
        client.invalidateQueries({ queryKey: key }),
        refetch()
      ])
    },
    retry: false,
    gcTime: 0
  })
  const submit = form.handleSubmit(() => save.mutate())
  return {
    form,
    connection,
    saved,
    pending: save.isPending,
    error: save.error,
    submit: () => void submit()
  }
}
