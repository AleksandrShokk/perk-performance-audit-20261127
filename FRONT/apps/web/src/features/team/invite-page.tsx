'use client'

import { ROLE_LABELS, inviteCodeFromURL } from '@app/analytics/permissions'
import { useMutation } from '@tanstack/react-query'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useEffect } from 'react'

import { teamAcceptInvite } from '@app/api'

import { ErrorNotice, Loading } from '@/components/feedback'
import { Button } from '@/components/ui/button'

import { useAuth } from '@/features/auth/auth-provider'
import { AuthFrame } from '@/features/auth/auth-screen'
import { useWorkspace } from '@/features/workspace/workspace-provider'

import { errorMessage } from '@/lib/errors'
import { browserSession } from '@/lib/http'

import { pendingInviteCode, usePendingInvite } from './pending-invite'

export function InvitePage() {
  const invite = usePendingInvite(),
    auth = useAuth(),
    scope = useWorkspace(),
    router = useRouter()
  useEffect(() => {
    if (!window.location.hash) return
    const code = inviteCodeFromURL(window.location.href)
    if (code) invite.remember(code)
    else invite.clear()
    history.replaceState(
      history.state,
      '',
      window.location.pathname + window.location.search
    )
  }, [invite])
  const accept = useMutation({
    mutationFn: async () => {
      const code = invite.code,
        epoch = browserSession.epoch
      if (!code) throw new Error('Откройте ссылку из письма')
      try {
        const result = await teamAcceptInvite({ code })
        if (epoch !== browserSession.epoch || pendingInviteCode() !== code)
          return
        invite.clear()
        await scope.refresh()
        if (epoch !== browserSession.epoch) return
        scope.selectWorkspace(result.workspace_id)
        router.replace('/')
      } catch (error) {
        throw new Error(errorMessage(error))
      }
    },
    retry: false,
    gcTime: 0
  })
  const switchAccount = useMutation({
    mutationFn: async () => {
      const code = invite.code
      await auth.signOut()
      if (code) invite.remember(code)
      router.replace('/login')
    },
    gcTime: 0
  })
  const signedIn = auth.status === 'authenticated'
  const wrongEmail =
    signedIn &&
    !!invite.details &&
    auth.user?.email.toLowerCase() !== invite.details.email.toLowerCase()
  const close = () => {
    invite.clear()
    router.replace(signedIn ? '/' : '/login')
  }
  return (
    <AuthFrame>
      <h1>Приглашение в команду</h1>
      {invite.pending || auth.status === 'loading' ? (
        <Loading />
      ) : !invite.code ? (
        <p className='muted'>Откройте ссылку из письма.</p>
      ) : invite.error ? (
        <ErrorNotice
          error={invite.error}
          onRetry={invite.retry}
        />
      ) : (
        invite.details && (
          <div className='form-stack'>
            <div className='invite-summary'>
              <h2>{invite.details.workspace_name}</h2>
              <p>{invite.details.email}</p>
              <span>
                {ROLE_LABELS[invite.details.role] ?? invite.details.role}
              </span>
            </div>
            {auth.status === 'error' ? (
              <ErrorNotice
                error={auth.error}
                onRetry={() => void auth.reload()}
              />
            ) : !signedIn ? (
              <>
                <Button asChild>
                  <Link href='/login'>Войти</Link>
                </Button>
                <Button
                  asChild
                  variant='outline'
                >
                  <Link href='/register'>Зарегистрироваться</Link>
                </Button>
              </>
            ) : wrongEmail ? (
              <>
                <p className='muted'>
                  Войдите с адресом {invite.details.email}.
                </p>
                <Button
                  disabled={switchAccount.isPending}
                  onClick={() => switchAccount.mutate()}
                >
                  Войти в другой аккаунт
                </Button>
              </>
            ) : !auth.user?.session_mfa_verified ? (
              <Button asChild>
                <Link href='/verify'>Подтвердить вход</Link>
              </Button>
            ) : !auth.user.strong_factor_enabled || !auth.user.phone ? (
              <Button asChild>
                <Link href='/phone'>Подтвердить телефон</Link>
              </Button>
            ) : (
              <Button
                disabled={accept.isPending}
                onClick={() => accept.mutate()}
              >
                {accept.isPending ? 'Присоединяемся…' : 'Присоединиться'}
              </Button>
            )}
          </div>
        )
      )}
      <ErrorNotice error={accept.error ?? switchAccount.error} />
      <Button
        variant='ghost'
        className='w-full mt-4'
        onClick={close}
      >
        Отмена
      </Button>
    </AuthFrame>
  )
}
