'use client'

import { ROLE_LABELS } from '@app/analytics/permissions'
import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation } from '@tanstack/react-query'
import Link from 'next/link'
import { useState } from 'react'
import { useForm } from 'react-hook-form'

import { type ChangePasswordValues, changePasswordSchema } from '@app/schemas'

import { authChangePassword } from '@app/api'

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

import { useAuth } from '@/features/auth/auth-provider'
import { ReportHint } from '@/features/finance/components/report-hint'
import { CopyValue } from '@/features/products/components/copy-value'
import { useWorkspace } from '@/features/workspace/workspace-provider'

import { useProtectedAction } from '@/hooks/use-protected-action'

import { browserSession } from '@/lib/http'

export function ProfileSettings() {
  const auth = useAuth(),
    scope = useWorkspace()
  const [ending, setEnding] = useState(false)
  return (
    <div className='settings-profile-grid'>
      <div>
        <section className='surface settings-section'>
          <h2>Профиль</h2>
          <dl className='settings-profile-values'>
            <div>
              <dt>Email</dt>
              <dd>
                <CopyValue
                  value={auth.user?.email || '—'}
                  label='email'
                />
              </dd>
            </div>
            <div>
              <dt>Телефон</dt>
              <dd>
                <Link
                  href='/phone'
                  className='text-link'
                >
                  {auth.user?.phone
                    ? `${auth.user.phone} · Сменить`
                    : 'Привязать'}
                </Link>
              </dd>
            </div>
            <div>
              <dt>Компания</dt>
              <dd>{scope.workspace?.name ?? '—'}</dd>
            </div>
            <div>
              <dt>Роль</dt>
              <dd>{ROLE_LABELS[scope.workspace?.role ?? ''] ?? '—'}</dd>
            </div>
          </dl>
        </section>
        <section className='surface settings-section'>
          <h2>Сессии</h2>
          <Button
            variant='outline'
            onClick={() => setEnding(true)}
          >
            Выйти на всех устройствах
          </Button>
        </section>
      </div>
      <PasswordForm />
      {ending && <EndSessions onClose={() => setEnding(false)} />}
    </div>
  )
}
function PasswordForm() {
  const form = useForm<ChangePasswordValues>({
    resolver: zodResolver(changePasswordSchema),
    defaultValues: { password: '', new_password: '' }
  })
  const save = useProtectedAction(
    signal =>
      authChangePassword(changePasswordSchema.parse(form.getValues()), {
        signal
      }),
    () => {
      form.reset()
      browserSession.end()
    },
    { refresh: false }
  )
  return (
    <section className='surface settings-section'>
      <div className='catalog-title'>
        <h2>Сменить пароль</h2>
        <ReportHint label='О смене пароля'>
          После смены пароля нужно войти заново на всех устройствах.
        </ReportHint>
      </div>
      <form
        className='settings-form'
        onSubmit={form.handleSubmit(() => save.mutate())}
      >
        <fieldset disabled={save.isPending}>
          <FormField
            label='Текущий пароль'
            error={form.formState.errors.password?.message}
          >
            <Input
              type='password'
              autoComplete='current-password'
              {...form.register('password')}
              maxLength={128}
            />
          </FormField>
          <FormField
            label='Новый пароль · от 15 символов'
            error={form.formState.errors.new_password?.message}
          >
            <Input
              type='password'
              autoComplete='new-password'
              {...form.register('new_password')}
              maxLength={128}
            />
          </FormField>
          <ErrorNotice error={save.error} />
          <Button
            type='submit'
            disabled={save.isPending}
          >
            {save.isPending ? 'Сохраняем…' : 'Сменить пароль'}
          </Button>
        </fieldset>
      </form>
    </section>
  )
}
function EndSessions({ onClose }: { onClose: () => void }) {
  const auth = useAuth()
  const save = useMutation({
    mutationFn: auth.signOutAll,
    gcTime: 0,
    retry: false
  })
  return (
    <Dialog
      open
      onOpenChange={open => {
        if (!open) onClose()
      }}
    >
      <DialogContent className='max-w-md'>
        <DialogHeader>
          <DialogTitle>Выйти на всех устройствах?</DialogTitle>
          <DialogDescription>
            На этом устройстве тоже потребуется войти заново.
          </DialogDescription>
        </DialogHeader>
        <ErrorNotice error={save.error} />
        <Button
          disabled={save.isPending}
          onClick={() => save.mutate()}
        >
          {save.isPending ? 'Завершаем…' : 'Завершить все сессии'}
        </Button>
        <Button
          variant='ghost'
          onClick={onClose}
        >
          Отмена
        </Button>
      </DialogContent>
    </Dialog>
  )
}
