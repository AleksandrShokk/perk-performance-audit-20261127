import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { View } from 'react-native'
import { z } from 'zod'

import {
  type InviteView,
  type MemberView,
  type RoleInput,
  teamCancelInvite,
  teamChangeRole,
  teamInvite,
  teamList,
  teamRemoveMember,
  teamResendInvite
} from '@app/api'

import {
  BottomSheet,
  Button,
  Card,
  Divider,
  ListRow,
  Notice,
  Screen,
  Skeleton,
  Text,
  TextField
} from '@/components/ui'

import { useAuth } from '@/features/auth/providers/AuthProvider'
import {
  StepUpCancelled,
  useStepUp
} from '@/features/auth/stepUp/StepUpProvider'
import { useWorkspace } from '@/features/workspace/providers/WorkspaceProvider'

import { useModalController } from '@/hooks/useModalController'

import { errorMessage } from '@/lib/errors'

import { AccessForm } from '../components/AccessForm'
import { ROLE_DEFAULTS, ROLE_LABELS } from '../model/permissions'

import { createStyles } from '@/theme'

export default function TeamScreen() {
  const styles = useStyles()
  const { user } = useAuth()
  const { workspace, stores, isAdmin, refetch } = useWorkspace()
  const client = useQueryClient()
  const withStepUp = useStepUp()
  const sheet = useModalController()
  const cancelled = useRef(false)
  useEffect(() => {
    cancelled.current = false
    return () => {
      cancelled.current = true
    }
  }, [])
  async function beforePrompt() {
    if (cancelled.current) throw new StepUpCancelled()
    await sheet.dismiss()
    if (cancelled.current) throw new StepUpCancelled()
  }
  function close() {
    cancelled.current = true
    void sheet.dismiss().then(() => setEditing(null))
  }
  const [editing, setEditing] = useState<MemberView | 'new' | null>(null)
  const [email, setEmail] = useState('')
  const [access, setAccess] = useState<RoleInput>({ role: 'manager' })
  const [confirmRemoval, setConfirmRemoval] = useState(false)
  const [sent, setSent] = useState(false)
  const key = ['user', user?.id, workspace?.id, 'team']
  const query = useQuery({
    queryKey: key,
    queryFn: () => teamList(workspace!.id),
    enabled: isAdmin && !!workspace,
    meta: { persist: false }
  })
  const refresh = () => client.invalidateQueries({ queryKey: key })
  const save = useMutation({
    mutationFn: () =>
      withStepUp(
        async () => {
          if (editing === 'new')
            await teamInvite(workspace!.id, {
              ...access,
              email: email.trim().toLowerCase()
            })
          else
            await teamChangeRole(
              workspace!.id,
              (editing as MemberView).user_id,
              access
            )
        },
        { beforePrompt }
      ),
    onError: () => {
      if (!cancelled.current) void sheet.open()
    },
    onSuccess: async () => {
      setSent(editing === 'new')
      await sheet.dismiss()
      setEditing(null)
      await refetch()
    },
    onSettled: () => {
      void refresh()
    }
  })
  const action = useMutation({
    mutationFn: ({
      kind,
      id
    }: {
      kind: 'remove' | 'cancel' | 'resend'
      id: string
    }) =>
      withStepUp(
        async () => {
          if (kind === 'remove') await teamRemoveMember(workspace!.id, id)
          if (kind === 'cancel') await teamCancelInvite(workspace!.id, id)
          if (kind === 'resend') await teamResendInvite(workspace!.id, id)
        },
        editing ? { beforePrompt } : undefined
      ),
    onError: () => {
      if (editing && !cancelled.current) void sheet.open()
    },
    onSuccess: async (_result, variables) => {
      if (variables.kind === 'remove') {
        await sheet.dismiss()
        setEditing(null)
        await refetch()
      }
      setSent(variables.kind === 'resend')
    },
    onSettled: () => {
      void refresh()
    }
  })

  const busy = save.isPending || action.isPending
  function open(member: MemberView | 'new') {
    cancelled.current = false
    void sheet.open()
    save.reset()
    action.reset()
    setSent(false)
    setConfirmRemoval(false)
    setEditing(member)
    setEmail(member === 'new' ? '' : member.email)
    setAccess(
      member === 'new'
        ? {
            role: 'manager',
            permissions: ROLE_DEFAULTS.manager,
            store_ids: stores.map(store => store.id)
          }
        : {
            role: member.role,
            permissions: member.permissions,
            store_ids: member.store_ids
          }
    )
  }
  if (!isAdmin)
    return (
      <Screen>
        <Notice message='Управление командой доступно владельцу и администратору.' />
      </Screen>
    )
  const formError = save.error ?? action.error
  return (
    <Screen
      bottomInset
      onRefresh={() => query.refetch()}
    >
      <View style={styles.sections}>
        <Text variant='screenTitle'>Команда</Text>
        <Button
          title='Пригласить сотрудника'
          disabled={busy}
          onPress={() => open('new')}
        />
        {sent && (
          <Notice
            tone='success'
            message='Приглашение отправлено на email.'
          />
        )}
        {query.error && (
          <Notice
            tone='error'
            message={errorMessage(query.error)}
          />
        )}
        {action.error &&
          !editing &&
          !(action.error instanceof StepUpCancelled) && (
            <Notice
              tone='error'
              message={errorMessage(action.error)}
            />
          )}
        {!query.data ? (
          <Skeleton height={180} />
        ) : (
          <>
            <Card>
              {query.data.members.map((member, index) => (
                <View key={member.user_id}>
                  {index > 0 && <Divider />}
                  <ListRow
                    title={member.email}
                    subtitle={`${ROLE_LABELS[member.role]}${member.is_creator ? ' · Создатель' : ''}`}
                    onPress={
                      member.is_creator || busy ? undefined : () => open(member)
                    }
                  />
                </View>
              ))}
            </Card>
            {!!query.data.invites.length && (
              <Text variant='sectionTitle'>Ожидают приглашения</Text>
            )}
            {query.data.invites.map(invite => (
              <InviteCard
                key={invite.id}
                invite={invite}
                busy={action.isPending}
                onResend={() =>
                  action.mutate({ kind: 'resend', id: invite.id })
                }
                onCancel={() =>
                  action.mutate({ kind: 'cancel', id: invite.id })
                }
              />
            ))}
          </>
        )}
      </View>
      <BottomSheet
        title={
          editing === 'new'
            ? 'Пригласить сотрудника'
            : (editing?.email ?? 'Команда')
        }
        visible={sheet.visible}
        onDismiss={sheet.onDismiss}
        onClose={close}
      >
        {editing && (
          <>
            {editing === 'new' && (
              <TextField
                label='Email сотрудника'
                value={email}
                onChangeText={setEmail}
                autoCapitalize='none'
                keyboardType='email-address'
                autoComplete='email'
              />
            )}
            <AccessForm
              value={access}
              onChange={setAccess}
              stores={stores}
            />
            {formError && !(formError instanceof StepUpCancelled) && (
              <Notice
                tone='error'
                message={errorMessage(formError)}
              />
            )}
            <Button
              title={
                editing === 'new' ? 'Отправить приглашение' : 'Сохранить права'
              }
              loading={save.isPending}
              disabled={
                editing === 'new' && !z.email().safeParse(email.trim()).success
              }
              onPress={() => save.mutate()}
            />
            {editing !== 'new' &&
              (confirmRemoval ? (
                <>
                  <Text>Убрать доступ сотрудника к этому кабинету?</Text>
                  <Button
                    title='Подтвердить удаление доступа'
                    variant='secondary'
                    loading={action.isPending}
                    onPress={() =>
                      action.mutate({ kind: 'remove', id: editing.user_id })
                    }
                  />
                </>
              ) : (
                <Button
                  title='Убрать доступ'
                  variant='ghost'
                  onPress={() => setConfirmRemoval(true)}
                />
              ))}
          </>
        )}
      </BottomSheet>
    </Screen>
  )
}

function InviteCard({
  invite,
  busy,
  onResend,
  onCancel
}: {
  invite: InviteView
  busy: boolean
  onResend: () => void
  onCancel: () => void
}) {
  const styles = useStyles()
  return (
    <Card>
      <Text variant='bodyStrong'>{invite.email}</Text>
      <Text
        variant='label'
        tone='secondary'
      >
        {ROLE_LABELS[invite.role]}
      </Text>
      <View style={styles.actions}>
        <Button
          title='Отправить ещё раз'
          variant='ghost'
          disabled={busy}
          onPress={onResend}
        />
        <Button
          title='Отменить'
          variant='ghost'
          disabled={busy}
          onPress={onCancel}
        />
      </View>
    </Card>
  )
}
const useStyles = createStyles(({ spacing }) => ({
  sections: { gap: spacing.lg, paddingTop: spacing.xxl },
  actions: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm }
}))
