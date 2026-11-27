'use client'

import { ROLE_LABELS } from '@app/analytics/permissions'
import { useQuery } from '@tanstack/react-query'
import { Check, Mail, Plus } from 'lucide-react'
import { useState } from 'react'
import { z } from 'zod'

import {
  type MemberView,
  type RoleInput,
  teamCancelInvite,
  teamChangeRole,
  teamInvite,
  teamList,
  teamRemoveMember,
  teamResendInvite
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
import { useWorkspace } from '@/features/workspace/workspace-provider'

import { useProtectedAction } from '@/hooks/use-protected-action'

import { settingsDate } from '../model/labels'

import { AccessForm } from './access-form'

type Session = { id: string; member: MemberView | null }
type InvitationAction = {
  id: string
  kind: 'resend' | 'cancel'
  inviteId: string
  email: string
}
export function TeamSettings() {
  const scope = useWorkspace(),
    { user } = useAuth()
  const [editor, setEditor] = useState<Session | null>(null)
  const [action, setAction] = useState<InvitationAction | null>(null)
  const [notice, setNotice] = useState('')
  const query = useQuery({
    queryKey: ['user', user?.id, scope.workspace?.id, 'team', scope.accessKey],
    queryFn: ({ signal }) => teamList(scope.workspace!.id, { signal }),
    enabled: scope.ready && !!scope.workspace && scope.admin,
    refetchInterval: 30000
  })
  const access = (member: MemberView) =>
    member.store_ids == null
      ? 'Все кабинеты'
      : `Кабинетов: ${member.store_ids.length}`
  return (
    <>
      <section
        className='surface settings-section'
        aria-label='Сотрудники компании'
      >
        <div className='section-heading'>
          <h2>Сотрудники</h2>
          <Button
            onClick={() => {
              setNotice('')
              setEditor({ id: crypto.randomUUID(), member: null })
            }}
          >
            <Plus size={15} />
            Пригласить сотрудника
          </Button>
        </div>
        <ErrorNotice
          error={query.error}
          onRetry={() => void query.refetch()}
        />
        {notice && (
          <p
            className='settings-saved'
            role='status'
          >
            <Check size={15} />
            {notice}
          </p>
        )}
        {query.isPending ? (
          <Skeleton className='h-48 w-full' />
        ) : query.data?.members.length ? (
          <div className='settings-table-scroll'>
            <table className='settings-data'>
              <thead>
                <tr>
                  <th>Email</th>
                  <th>Роль</th>
                  <th>Доступ</th>
                  <th>
                    <span className='sr-only'>Действия</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {query.data.members.map(member => (
                  <tr key={member.user_id}>
                    <td>
                      <strong>{member.email}</strong>
                      {member.user_id === user?.id && <small>Вы</small>}
                    </td>
                    <td>{ROLE_LABELS[member.role] ?? member.role}</td>
                    <td>{access(member)}</td>
                    <td>
                      {!member.is_creator && member.role !== 'owner' && (
                        <Button
                          variant='outline'
                          size='sm'
                          aria-label={`Изменить доступ ${member.email}`}
                          onClick={() => {
                            setNotice('')
                            setEditor({ id: crypto.randomUUID(), member })
                          }}
                        >
                          Изменить доступ
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          !query.error && <Empty title='Сотрудников пока нет' />
        )}
      </section>
      <section
        className='surface settings-section'
        aria-label='Приглашения сотрудникам'
      >
        <div className='section-heading'>
          <h2>Приглашения</h2>
          <Mail
            size={16}
            className='text-muted-foreground'
          />
        </div>
        {query.isPending ? (
          <Skeleton className='h-28 w-full' />
        ) : query.data?.invites.length ? (
          <div className='settings-table-scroll'>
            <table className='settings-data'>
              <thead>
                <tr>
                  <th>Email</th>
                  <th>Роль</th>
                  <th>Действует до</th>
                  <th>
                    <span className='sr-only'>Действия</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {query.data.invites.map(invite => (
                  <tr key={invite.id}>
                    <td>{invite.email}</td>
                    <td>{ROLE_LABELS[invite.role]}</td>
                    <td>{settingsDate(invite.expires_at)}</td>
                    <td className='settings-row-actions'>
                      <Button
                        variant='ghost'
                        size='sm'
                        aria-label={`Отправить снова ${invite.email}`}
                        onClick={() =>
                          setAction({
                            id: crypto.randomUUID(),
                            kind: 'resend',
                            inviteId: invite.id,
                            email: invite.email
                          })
                        }
                      >
                        Отправить снова
                      </Button>
                      <Button
                        variant='ghost'
                        size='sm'
                        aria-label={`Отменить приглашение ${invite.email}`}
                        onClick={() =>
                          setAction({
                            id: crypto.randomUUID(),
                            kind: 'cancel',
                            inviteId: invite.id,
                            email: invite.email
                          })
                        }
                      >
                        Отменить
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          !query.error && <Empty title='Ожидающих приглашений нет' />
        )}
      </section>
      {editor && (
        <MemberEditor
          key={editor.id}
          member={editor.member}
          onClose={() =>
            setEditor(current => (current?.id === editor.id ? null : current))
          }
          onSaved={message => {
            setNotice(message)
            setEditor(current => (current?.id === editor.id ? null : current))
          }}
        />
      )}
      {action && (
        <InviteAction
          key={action.id}
          action={action}
          onClose={() =>
            setAction(current => (current?.id === action.id ? null : current))
          }
          onSaved={() => {
            setNotice(
              action.kind === 'resend'
                ? 'Приглашение отправлено'
                : 'Приглашение отменено'
            )
            setAction(current => (current?.id === action.id ? null : current))
          }}
        />
      )}
    </>
  )
}
function MemberEditor({
  member,
  onClose,
  onSaved
}: {
  member: MemberView | null
  onClose: () => void
  onSaved: (message: string) => void
}) {
  const scope = useWorkspace()
  const [email, setEmail] = useState('')
  const [validation, setValidation] = useState('')
  const [access, setAccess] = useState<RoleInput>(
    member
      ? {
          role: member.role as RoleInput['role'],
          permissions: member.permissions,
          store_ids: member.store_ids
        }
      : { role: 'manager', store_ids: null }
  )
  const [removing, setRemoving] = useState(false)
  const save = useProtectedAction(
    async signal => {
      if(member) await teamChangeRole(scope.workspace!.id,member.user_id,access,{signal})
      else await teamInvite(scope.workspace!.id,{...access,email:email.trim().toLowerCase()},{signal})
    },
    ()=>onSaved(member ? 'Права сохранены':'Приглашение отправлено')
  )
  const remove = useProtectedAction(
    signal =>
      teamRemoveMember(scope.workspace!.id, member!.user_id, { signal }),
    () => onSaved('Сотрудник удалён')
  )
  const busy = save.isPending || remove.isPending
  return (
    <Dialog
      open
      onOpenChange={open => {
        if (!open) onClose()
      }}
    >
      <DialogContent className='settings-dialog'>
        <DialogHeader>
          <DialogTitle>
            {removing
              ? 'Удалить сотрудника?'
              : member
                ? 'Доступ сотрудника'
                : 'Пригласить сотрудника'}
          </DialogTitle>
          <DialogDescription>
            {member?.email ?? 'Ссылка придёт сотруднику на почту.'}
          </DialogDescription>
        </DialogHeader>
        <div className='settings-dialog-scroll'>
          {removing ? (
            <div className='form-stack'>
              <ErrorNotice error={remove.error} />
              <Button
                variant='destructive'
                disabled={busy}
                onClick={() => remove.mutate()}
              >
                {remove.isPending ? 'Удаляем…' : 'Удалить сотрудника'}
              </Button>
              <Button
                variant='ghost'
                disabled={busy}
                onClick={() => setRemoving(false)}
              >
                Назад
              </Button>
            </div>
          ) : (
            <form
              className='settings-form'
              onSubmit={event => {
                event.preventDefault()
                setValidation('')
                if (!member) {
                  const parsed = z
                    .string()
                    .trim()
                    .email('Введите корректный email')
                    .safeParse(email)
                  if (!parsed.success) {
                    setValidation(
                      parsed.error.issues[0]?.message ?? 'Проверьте email'
                    )
                    return
                  }
                }
                save.mutate()
              }}
            >
              <fieldset disabled={busy}>
                {!member && (
                  <FormField
                    label='Email сотрудника'
                    error={validation}
                  >
                    <Input
                      type='email'
                      value={email}
                      maxLength={254}
                      autoComplete='email'
                      onChange={event => setEmail(event.target.value)}
                    />
                  </FormField>
                )}
                <AccessForm
                  value={access}
                  onChange={setAccess}
                  stores={scope.connections}
                />
                <ErrorNotice error={save.error} />
                <Button
                  type='submit'
                  disabled={busy}
                >
                  {save.isPending
                    ? 'Сохраняем…'
                    : member
                      ? 'Сохранить доступ'
                      : 'Отправить приглашение'}
                </Button>
                {member && (
                  <Button
                    type='button'
                    variant='ghost'
                    className='settings-remove'
                    onClick={() => setRemoving(true)}
                  >
                    Удалить сотрудника
                  </Button>
                )}
              </fieldset>
            </form>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
function InviteAction({
  action,
  onClose,
  onSaved
}: {
  action: InvitationAction
  onClose: () => void
  onSaved: () => void
}) {
  const scope = useWorkspace()
  const save = useProtectedAction(async signal => {
    if(action.kind === 'resend') await teamResendInvite(scope.workspace!.id,action.inviteId,{signal})
    else await teamCancelInvite(scope.workspace!.id,action.inviteId,{signal})
  },onSaved)
  return (
    <Dialog
      open
      onOpenChange={open => {
        if (!open) onClose()
      }}
    >
      <DialogContent className='max-w-md'>
        <DialogHeader>
          <DialogTitle>
            {action.kind === 'resend'
              ? 'Отправить приглашение снова?'
              : 'Отменить приглашение?'}
          </DialogTitle>
          <DialogDescription>{action.email}</DialogDescription>
        </DialogHeader>
        <ErrorNotice error={save.error} />
        <Button
          disabled={save.isPending}
          onClick={() => save.mutate()}
        >
          {save.isPending
            ? 'Выполняем…'
            : action.kind === 'resend'
              ? 'Отправить'
              : 'Отменить приглашение'}
        </Button>
        <Button
          variant='ghost'
          onClick={onClose}
        >
          Закрыть
        </Button>
      </DialogContent>
    </Dialog>
  )
}
