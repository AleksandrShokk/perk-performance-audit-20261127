'use client'

import { inviteCodeFromURL } from '@app/analytics/permissions'
import { useQuery } from '@tanstack/react-query'
import { usePathname, useRouter } from 'next/navigation'
import {
  type ReactNode,
  createContext,
  use,
  useEffect,
  useMemo,
  useSyncExternalStore
} from 'react'

import { teamPreviewInvite } from '@app/api'

import { useAuth } from '@/features/auth/auth-provider'

import { errorMessage } from '@/lib/errors'
import { browserSession } from '@/lib/http'

const storageKey = 'perk.web.pending-invite'
let fallback: string | null = null
function rawEntry() {
  try {
    return sessionStorage.getItem(storageKey)
  } catch {
    return fallback
  }
}
function validEntry(raw: string | null): { code: string; id: string } | null {
  try {
    const value = JSON.parse(raw ?? 'null')
    return value &&
      typeof value.id === 'string' &&
      typeof value.code === 'string' &&
      inviteCodeFromURL(`#code=${value.code}`) === value.code
      ? value
      : null
  } catch {
    return null
  }
}
export function pendingInviteCode() {
  return typeof window === 'undefined'
    ? null
    : (validEntry(rawEntry())?.code ?? null)
}
function update(value: string | null) {
  fallback = value
  try {
    if (value) sessionStorage.setItem(storageKey, value)
    else sessionStorage.removeItem(storageKey)
  } catch {}
  window.dispatchEvent(new Event('perk-invite'))
}
function subscribe(listener: () => void) {
  window.addEventListener('perk-invite', listener)
  window.addEventListener('storage', listener)
  return () => {
    window.removeEventListener('perk-invite', listener)
    window.removeEventListener('storage', listener)
  }
}
const serverSnapshot = () => null
type InviteContext = {
  code: string | null
  details: Awaited<ReturnType<typeof teamPreviewInvite>> | undefined
  pending: boolean
  error: unknown
  remember: (code: string) => void
  clear: () => void
  retry: () => void
}
const Context = createContext<InviteContext | null>(null)
export function PendingInviteProvider({ children }: { children: ReactNode }) {
  const raw = useSyncExternalStore(subscribe, rawEntry, serverSnapshot)
  const entry = useMemo(() => validEntry(raw), [raw])
  const auth = useAuth(),
    pathname = usePathname(),
    router = useRouter()
  const preview = useQuery({
    queryKey: ['invite-preview', entry?.id ?? 'none'],
    queryFn: async ({ signal }) => {
      try {
        return await teamPreviewInvite({ code: entry!.code }, { signal })
      } catch (error) {
        throw new Error(errorMessage(error))
      }
    },
    enabled: !!entry,
    gcTime: 0,
    staleTime: 60000,
    retry: false
  })
  useEffect(() => browserSession.subscribe(() => update(null)), [])
  useEffect(() => {
    if (
      !entry ||
      !preview.data ||
      preview.error ||
      auth.status !== 'authenticated' ||
      !auth.user?.session_mfa_verified ||
      !auth.user.strong_factor_enabled
    )
      return
    if (
      ['/login', '/register', '/verify', '/'].includes(pathname) ||
      (pathname === '/phone' && !!auth.user.phone)
    )
      router.replace('/invite')
  }, [
    entry,
    preview.data,
    preview.error,
    auth.status,
    auth.user,
    pathname,
    router
  ])
  return (
    <Context
      value={{
        code: entry?.code ?? null,
        details: preview.data,
        pending: !!entry && preview.isPending,
        error: preview.error,
        remember: code => {
          if (inviteCodeFromURL(`#code=${code}`) === code)
            update(JSON.stringify({ id: crypto.randomUUID(), code }))
        },
        clear: () => update(null),
        retry: () => void preview.refetch()
      }}
    >
      {children}
    </Context>
  )
}
export function usePendingInvite() {
  const value = use(Context)
  if (!value) throw new Error('Нет провайдера приглашения')
  return value
}
