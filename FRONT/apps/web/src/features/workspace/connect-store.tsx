'use client'

import { initialImportMessage } from '@app/analytics/onboarding'
import { Plus } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useForm } from 'react-hook-form'

import { connectOzonSchema, connectStoreSchema } from '@app/schemas'

import { storeConnectOzon, storeConnectWildberries } from '@app/api'

import { ErrorNotice } from '@/components/feedback'
import { FormField } from '@/components/form-field'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'

import { useProtectedAction } from '@/hooks/use-protected-action'

import { ApiKeyGuide } from './api-key-guide'
import { useWorkspace } from './workspace-provider'

type Values = {
  name: string
  token: string
  client_id: string
  api_key: string
}
export function ConnectStore({ compact = false }: { compact?: boolean }) {
  const scope = useWorkspace()
  const [session, setSession] = useState<string | null>(null)
  if (!scope.admin || !scope.workspace) return null
  return (
    <>
      <Button
        className={compact ? 'connect-store-trigger' : undefined}
        variant={compact ? 'ghost' : 'default'}
        size={compact ? 'sm' : 'default'}
        onClick={() => setSession(crypto.randomUUID())}
      >
        <Plus size={16} />
        {compact ? 'Добавить' : 'Подключить кабинет'}
      </Button>
      {session && (
        <ConnectionForm
          key={session}
          onClose={() =>
            setSession(current => (current === session ? null : current))
          }
        />
      )}
    </>
  )
}
function ConnectionForm({ onClose }: { onClose: () => void }) {
  const scope = useWorkspace()
  const live = useRef(true)
  useEffect(() => {
    live.current = true
    return () => {
      live.current = false
    }
  }, [])
  const [provider, setProvider] = useState<'wildberries' | 'ozon'>(
    'wildberries'
  )
  const form = useForm<Values>({
    defaultValues: { name: '', token: '', client_id: '', api_key: '' }
  })
  const save = useProtectedAction(
    signal =>
      provider === 'ozon'
        ? storeConnectOzon(
            scope.workspace!.id,
            connectOzonSchema.parse(form.getValues()),
            { signal }
          )
        : storeConnectWildberries(
            scope.workspace!.id,
            connectStoreSchema.parse(form.getValues()),
            { signal }
          ),
    async store => {
      form.reset()
      await scope.refresh()
      if (live.current) {
        scope.selectStore(store.id)
        scope.showImportNotice(store.name)
        onClose()
      }
    },
    { refresh: false }
  )
  const select = (value: typeof provider) => {
    setProvider(value)
    form.setValue('token', '')
    form.setValue('api_key', '')
    form.setValue('client_id', '')
    form.clearErrors()
  }
  return (
    <Dialog
      open
      onOpenChange={open => {
        if (!open) onClose()
      }}
    >
      <DialogContent className='max-w-md'>
        <DialogHeader>
          <DialogTitle>Новый кабинет</DialogTitle>
          <DialogDescription>{initialImportMessage}</DialogDescription>
        </DialogHeader>
        <form
          className='form-stack'
          onSubmit={form.handleSubmit(values => {
            const parsed = (
              provider === 'ozon' ? connectOzonSchema : connectStoreSchema
            ).safeParse(values)
            form.clearErrors()
            if (!parsed.success) {
              for (const issue of parsed.error.issues)
                form.setError(issue.path[0] as keyof Values, {
                  message: issue.message
                })
              return
            }
            save.mutate()
          })}
        >
          <fieldset
            disabled={save.isPending}
            className='form-stack'
          >
            <div className='period-segments'>
              <button
                type='button'
                aria-pressed={provider === 'wildberries'}
                onClick={() => select('wildberries')}
              >
                Wildberries
              </button>
              <button
                type='button'
                aria-pressed={provider === 'ozon'}
                onClick={() => select('ozon')}
              >
                Ozon
              </button>
            </div>
            <FormField
              label='Название магазина'
              error={form.formState.errors.name?.message}
            >
              <Input
                {...form.register('name')}
                autoComplete='off'
              />
            </FormField>
            {provider === 'ozon' && (
              <FormField
                label='Client ID'
                error={form.formState.errors.client_id?.message}
              >
                <Input
                  {...form.register('client_id')}
                  autoComplete='off'
                  inputMode='numeric'
                />
              </FormField>
            )}
            <FormField
              label={provider === 'ozon' ? 'API Key' : 'API-токен Wildberries'}
              error={
                provider === 'ozon'
                  ? form.formState.errors.api_key?.message
                  : form.formState.errors.token?.message
              }
            >
              <Input
                {...form.register(provider === 'ozon' ? 'api_key' : 'token')}
                type='password'
                autoComplete='new-password'
                spellCheck={false}
              />
            </FormField>
            <ApiKeyGuide marketplace={provider} />
            <ErrorNotice error={save.error} />
            <Button type='submit'>
              {save.isPending ? 'Подключаем…' : 'Подключить'}
            </Button>
          </fieldset>
        </form>
      </DialogContent>
    </Dialog>
  )
}
