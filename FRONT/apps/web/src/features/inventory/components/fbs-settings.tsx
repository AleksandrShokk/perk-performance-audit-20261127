'use client'

import { useMutation, useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'

import {
  type InventorySettingsInput,
  inventorySettingsGet,
  inventorySettingsSave
} from '@app/api'

import { ErrorNotice, Loading } from '@/components/feedback'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog'

import { useWorkspace } from '@/features/workspace/workspace-provider'

import { useRefreshWorkspace } from '@/hooks/use-refresh-workspace'

export function FbsSettings({
  queryKey,
  onClose
}: {
  queryKey: unknown[]
  onClose: () => void
}) {
  const { workspace } = useWorkspace()
  const refresh = useRefreshWorkspace()
  const mounted = useRef(true)
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])
  const [selected, setSelected] = useState<
    InventorySettingsInput['fbs_mode'] | null
  >(null)
  const query = useQuery({
    queryKey: [...queryKey, 'settings'],
    queryFn: ({ signal }) => inventorySettingsGet(workspace!.id, { signal })
  })
  const value =
    selected ??
    (query.data?.fbs_mode === 'unknown' ? null : query.data?.fbs_mode)
  const save = useMutation({
    mutationFn: (fbs_mode: InventorySettingsInput['fbs_mode']) =>
      inventorySettingsSave(workspace!.id, { fbs_mode }),
    onSuccess: async () => {
      await refresh()
      if (mounted.current) onClose()
    }
  })
  return (
    <Dialog
      open
      onOpenChange={open => {
        if (!open) onClose()
      }}
    >
      <DialogContent className='stock-settings-dialog'>
        <DialogHeader>
          <DialogTitle>Учёт FBS</DialogTitle>
          <DialogDescription>
            Как устроены склады ваших кабинетов?
          </DialogDescription>
        </DialogHeader>
        {query.isPending ? (
          <Loading />
        ) : query.error ? (
          <ErrorNotice
            error={query.error}
            onRetry={() => void query.refetch()}
          />
        ) : (
          <form
            onSubmit={event => {
              event.preventDefault()
              if (value) save.mutate(value)
            }}
          >
            <fieldset disabled={save.isPending}>
              <legend className='sr-only'>Склады FBS</legend>
              {(['separate', 'shared'] as const).map(mode => (
                <label
                  key={mode}
                  className='stock-setting-option'
                >
                  <input
                    type='radio'
                    name='fbs-mode'
                    value={mode}
                    checked={value === mode}
                    onChange={() => setSelected(mode)}
                  />
                  <span>
                    {mode === 'separate' ? 'Разные склады' : 'Общий склад'}
                    <small>
                      {mode === 'separate'
                        ? 'Складывать остатки кабинетов'
                        : 'Смотреть остатки по кабинетам'}
                    </small>
                  </span>
                </label>
              ))}
            </fieldset>
            <ErrorNotice error={save.error} />
            <Button
              className='w-full'
              type='submit'
              disabled={!value || save.isPending}
            >
              {save.isPending ? 'Сохраняем…' : 'Сохранить'}
            </Button>
          </form>
        )}
      </DialogContent>
    </Dialog>
  )
}
