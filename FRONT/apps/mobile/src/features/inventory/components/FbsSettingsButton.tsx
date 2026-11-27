import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { inventorySettingsGet, inventorySettingsSave } from '@app/api'

import { BottomSheet, Button, Notice, Text } from '@/components/ui'

import { useAuth } from '@/features/auth/providers/AuthProvider'
import { useWorkspace } from '@/features/workspace/providers/WorkspaceProvider'

import { useModalController } from '@/hooks/useModalController'

import { errorMessage } from '@/lib/errors'

export function FbsSettingsButton() {
  const { user } = useAuth()
  const { workspace, isAdmin, allStores } = useWorkspace()
  const client = useQueryClient()
  const modal = useModalController()
  const query = useQuery({
    queryKey: ['user', user?.id, workspace?.id, 'inventory-settings'],
    queryFn: ({ signal }) => inventorySettingsGet(workspace!.id, { signal }),
    enabled: !!workspace && isAdmin && allStores,
    meta: { persist: false }
  })
  const save = useMutation({
    mutationFn: (fbs_mode: 'separate' | 'shared') =>
      inventorySettingsSave(workspace!.id, { fbs_mode }),
    onSuccess: data => {
      client.setQueryData(
        ['user', user?.id, workspace?.id, 'inventory-settings'],
        data
      )
      void client.invalidateQueries({
        queryKey: ['user', user?.id, workspace?.id]
      })
      void modal.dismiss()
    }
  })
  if (!isAdmin || !allStores) return null
  return (
    <>
      <Button
        title='Учёт складов FBS'
        variant='ghost'
        onPress={() => void modal.open()}
      />
      <BottomSheet
        title='Склады FBS'
        visible={modal.visible}
        onDismiss={modal.onDismiss}
        onClose={() => void modal.dismiss()}
      >
        <Text>
          Остатки разных кабинетов хранятся на разных физических складах?
        </Text>
        {query.error && (
          <Notice
            tone='error'
            message={errorMessage(query.error)}
          />
        )}
        {save.error && (
          <Notice
            tone='error'
            message={errorMessage(save.error)}
          />
        )}
        <Button
          title='Разные склады — складывать остатки'
          variant={
            query.data?.fbs_mode === 'separate' ? 'primary' : 'secondary'
          }
          loading={save.isPending && save.variables === 'separate'}
          disabled={save.isPending}
          onPress={() => save.mutate('separate')}
        />
        <Button
          title='Общий склад — смотреть по кабинетам'
          variant={query.data?.fbs_mode === 'shared' ? 'primary' : 'secondary'}
          loading={save.isPending && save.variables === 'shared'}
          disabled={save.isPending}
          onPress={() => save.mutate('shared')}
        />
      </BottomSheet>
    </>
  )
}
