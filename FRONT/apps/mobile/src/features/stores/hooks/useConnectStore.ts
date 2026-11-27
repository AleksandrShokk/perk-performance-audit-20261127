import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { router } from 'expo-router'
import { useState } from 'react'
import { useForm } from 'react-hook-form'

import { type ConnectStoreValues, connectStoreSchema } from '@app/schemas'

import {
  type StoreResponse,
  storeConfigureSync,
  storeConnectWildberries
} from '@app/api'

import { useStepUp } from '@/features/auth/stepUp/StepUpProvider'
import { useWorkspace } from '@/features/workspace/providers/WorkspaceProvider'

/** Создание магазина и запуск загрузки раздельны: не создаём дубль при повторе расписания. */
export function useConnectStore() {
  const { workspace, selectStore } = useWorkspace()
  const withStepUp = useStepUp()
  const queryClient = useQueryClient()
  const [connected, setConnected] = useState<StoreResponse | null>(null)
  const form = useForm<ConnectStoreValues>({
    resolver: zodResolver(connectStoreSchema),
    defaultValues: { name: '', token: '' }
  })
  const connection = useMutation({
    mutationFn: async (values: ConnectStoreValues) => {
      if (!workspace) throw new Error('Кабинет ещё не загружен')
      let store = connected
      if (!store) {
        store = await withStepUp(() =>
          storeConnectWildberries(workspace.id, values)
        )
        setConnected(store)
        // Ключ больше не нужен телефону. Не хранить в формах или кэше.
        form.setValue('token', '')
      }
      await storeConfigureSync(workspace.id, store.id, {
        enabled: true,
        sources: [
          'catalog',
          'sales',
          'orders',
          'finance',
          'stocks',
          'stock_history',
          'supply_demand',
          'supplies',
          'prices',
          'fbs',
          'funnel',
          'returns',
          'balance'
        ],
        recent_days: 30,
        load_history: true
      })
      return store
    },
    onSuccess: async store => {
      await queryClient.invalidateQueries({
        predicate: query => query.queryKey.includes('stores')
      })
      selectStore(store.id)
      router.replace('/(tabs)')
    },
    gcTime: 0
  })

  const submit = form.handleSubmit(values => connection.mutate(values))
  return {
    form,
    connected,
    submit: () =>
      connected
        ? connection.mutate({ name: connected.name, token: '' })
        : void submit(),
    pending: connection.isPending,
    error: connection.error
  }
}
