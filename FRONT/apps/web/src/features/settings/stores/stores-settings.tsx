'use client'

import { useQuery } from '@tanstack/react-query'
import { Check, RefreshCw } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'

import { replaceOzonKeySchema, replaceStoreTokenSchema } from '@app/schemas'

import {
  type StoreResponse,
  storeCheckConnection,
  storeConnectionStatus,
  storeRename,
  storeReplaceCredential,
  storeReplaceOzonCredential
} from '@app/api'

import { Empty, ErrorNotice } from '@/components/feedback'
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
import { Skeleton } from '@/components/ui/skeleton'

import { useAuth } from '@/features/auth/auth-provider'
import { ReportHint } from '@/features/finance/components/report-hint'
import { CopyValue } from '@/features/products/components/copy-value'
import { platformName } from '@/features/products/model/catalog'
import { ConnectStore } from '@/features/workspace/connect-store'
import { useWorkspace } from '@/features/workspace/workspace-provider'

import { useProtectedAction } from '@/hooks/use-protected-action'

import { connectionLabel, settingsDate } from '../model/labels'

export function StoresSettings() {
  const scope = useWorkspace()
  const [selection, setSelection] = useState<{
    id: string
    storeId: string
  } | null>(null)
  const selected = scope.connections.find(
    store => store.id === selection?.storeId
  )
  return (
    <>
      <section
        className='surface settings-section'
        aria-label='Кабинеты компании'
      >
        <div className='section-heading'>
          <h2>Кабинеты</h2>
          <ConnectStore />
        </div>
        {scope.connections.length ? (
          <div className='settings-table-scroll'>
            <table className='settings-data'>
              <thead>
                <tr>
                  <th>Кабинет</th>
                  <th>Площадка</th>
                  <th>Подключение</th>
                  <th>Проверено</th>
                  <th>
                    <span className='sr-only'>Действие</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {scope.connections.map(store => (
                  <tr key={store.id}>
                    <td>
                      <strong>{store.name}</strong>
                    </td>
                    <td>{platformName(store.marketplace)}</td>
                    <td>
                      <span
                        className={`connection-status ${store.connection_status}`}
                      >
                        {connectionLabel(store.connection_status)}
                      </span>
                    </td>
                    <td>{settingsDate(store.last_checked_at, true)}</td>
                    <td>
                      <Button
                        variant='outline'
                        size='sm'
                        aria-label={`Настроить ${store.name}`}
                        onClick={() =>
                          setSelection({
                            id: crypto.randomUUID(),
                            storeId: store.id
                          })
                        }
                      >
                        Настроить
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty title='Подключите первый кабинет' />
        )}
      </section>
      {selection && selected && (
        <StoreEditor
          key={selection.id}
          store={selected}
          onClose={() =>
            setSelection(current =>
              current?.id === selection.id ? null : current
            )
          }
        />
      )}
    </>
  )
}
function StoreEditor({
  store,
  onClose
}: {
  store: StoreResponse
  onClose: () => void
}) {
  const scope = useWorkspace(),
    { user } = useAuth()
  const connection = useQuery({
    queryKey: [
      'user',
      user?.id,
      scope.workspace?.id,
      'store-connection',
      store.id,
      scope.accessKey
    ],
    queryFn: ({ signal }) =>
      storeConnectionStatus(scope.workspace!.id, store.id, { signal }),
    staleTime: 0
  })
  const name = useForm({ defaultValues: { name: store.name } })
  const secret = useForm({ defaultValues: { token: '', api_key: '' } })
  const [notice, setNotice] = useState('')
  const rename = useProtectedAction(
    signal => {
      const value = z
        .string()
        .trim()
        .min(1, 'Введите название')
        .max(100, 'Не больше 100 символов')
        .parse(name.getValues('name'))
      return storeRename(
        scope.workspace!.id,
        store.id,
        { name: value },
        { signal }
      )
    },
    () => {
      name.reset({ name: name.getValues('name').trim() })
      setNotice('Название сохранено')
    }
  )
  const check = useProtectedAction(
    signal => storeCheckConnection(scope.workspace!.id, store.id, { signal }),
    () => setNotice('Подключение проверено')
  )
  const replace = useProtectedAction(
    signal => {
      if (store.marketplace === 'ozon') {
        const client_id = connection.data?.client_id
        if (!client_id) throw new Error('Дождитесь данных подключения')
        return storeReplaceOzonCredential(
          scope.workspace!.id,
          store.id,
          { client_id, ...replaceOzonKeySchema.parse(secret.getValues()) },
          { signal }
        )
      }
      return storeReplaceCredential(
        scope.workspace!.id,
        store.id,
        replaceStoreTokenSchema.parse(secret.getValues()),
        { signal }
      )
    },
    () => {
      secret.reset()
      setNotice('Ключ обновлён')
    }
  )
  const busy = rename.isPending || check.isPending || replace.isPending
  const provider = store.marketplace === 'ozon'
  return (
    <Dialog
      open
      onOpenChange={open => {
        if (!open) onClose()
      }}
    >
      <DialogContent className='settings-dialog'>
        <DialogHeader>
          <DialogTitle>{store.name}</DialogTitle>
          <DialogDescription>
            {platformName(store.marketplace)}
          </DialogDescription>
        </DialogHeader>
        <div className='settings-dialog-scroll'>
          <form
            className='settings-form'
            onSubmit={name.handleSubmit(values => {
              const parsed = z
                .string()
                .trim()
                .min(1, 'Введите название')
                .max(100, 'Не больше 100 символов')
                .safeParse(values.name)
              if (!parsed.success) {
                name.setError('name', {
                  message: parsed.error.issues[0]?.message
                })
                return
              }
              setNotice('')
              rename.mutate()
            })}
          >
            <fieldset disabled={busy}>
              <FormField
                label='Название кабинета'
                error={name.formState.errors.name?.message}
              >
                <Input
                  {...name.register('name')}
                  maxLength={100}
                  autoComplete='off'
                />
              </FormField>
              <Button
                variant='outline'
                type='submit'
                disabled={busy || !name.formState.isDirty}
              >
                {rename.isPending ? 'Сохраняем…' : 'Сохранить название'}
              </Button>
            </fieldset>
          </form>
          <div className='settings-connection'>
            <h3>Подключение</h3>
            {connection.isPending ? (
              <Skeleton className='h-20 w-full' />
            ) : (
              <dl>
                <div>
                  <dt>Статус</dt>
                  <dd>
                    {connectionLabel(
                      connection.data?.status ?? store.connection_status
                    )}
                  </dd>
                </div>
                {provider ? (
                  <div>
                    <dt>Client ID</dt>
                    <dd>
                      <CopyValue
                        value={connection.data?.client_id || '—'}
                        label='Client ID'
                      />
                    </dd>
                  </div>
                ) : (
                  <div>
                    <dt>Токен действует до</dt>
                    <dd>{settingsDate(connection.data?.expires_at)}</dd>
                  </div>
                )}
                <div>
                  <dt>Проверено</dt>
                  <dd>{settingsDate(connection.data?.checked_at, true)}</dd>
                </div>
              </dl>
            )}
            <ErrorNotice
              error={connection.error}
              onRetry={() => void connection.refetch()}
            />
            <Button
              variant='ghost'
              disabled={busy || connection.isPending}
              onClick={() => {
                setNotice('')
                check.mutate()
              }}
            >
              <RefreshCw size={14} />
              {check.isPending ? 'Проверяем…' : 'Проверить подключение'}
            </Button>
          </div>
          <form
            className='settings-form'
            onSubmit={secret.handleSubmit(values => {
              const parsed = (
                provider ? replaceOzonKeySchema : replaceStoreTokenSchema
              ).safeParse(values)
              secret.clearErrors()
              if (!parsed.success) {
                for (const issue of parsed.error.issues)
                  secret.setError(issue.path[0] as 'token' | 'api_key', {
                    message: issue.message
                  })
                return
              }
              setNotice('')
              replace.mutate()
            })}
          >
            <div className='catalog-title'>
              <h3>Заменить ключ</h3>
              <ReportHint label='О замене ключа'>
                {provider
                  ? 'Создайте новый Seller API Key для того же Client ID.'
                  : 'Создайте ключ WB только для чтения для того же продавца.'}{' '}
                Данные кабинета сохранятся.
              </ReportHint>
            </div>
            <fieldset disabled={busy}>
              <FormField
                label={provider ? 'Новый API Key' : 'Новый API-токен'}
                error={
                  provider
                    ? secret.formState.errors.api_key?.message
                    : secret.formState.errors.token?.message
                }
              >
                <Input
                  {...secret.register(provider ? 'api_key' : 'token')}
                  type='password'
                  autoComplete='new-password'
                  maxLength={provider ? 512 : 8192}
                  spellCheck={false}
                />
              </FormField>
              <Button
                type='submit'
                disabled={busy || (provider && !connection.data?.client_id)}
              >
                {replace.isPending ? 'Сохраняем…' : 'Сохранить ключ'}
              </Button>
            </fieldset>
          </form>
          <ErrorNotice error={rename.error ?? check.error ?? replace.error} />
          {notice && (
            <p
              className='settings-saved'
              role='status'
            >
              <Check size={15} />
              {notice}
            </p>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
