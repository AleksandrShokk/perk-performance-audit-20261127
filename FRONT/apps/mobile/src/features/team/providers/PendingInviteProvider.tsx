import { useQuery } from '@tanstack/react-query'
import { useLinkingURL } from 'expo-linking'
import {
  type ReactNode,
  createContext,
  use,
  useEffect,
  useRef,
  useState
} from 'react'

import { teamPreviewInvite } from '@app/api'

import { deleteInvite, readInvite, saveInvite } from '../model/inviteStorage'
import { inviteCodeFromURL } from '../model/permissions'

type PendingInvite = ReturnType<typeof useInviteState>
const Context = createContext<PendingInvite | null>(null)

function useInviteState() {
  const url = useLinkingURL()
  const incoming = inviteCodeFromURL(url)
  const [code, setCode] = useState<string | null>(incoming)
  const [ready, setReady] = useState(!!incoming)
  const changed = useRef(false)
  const lastURL = useRef(incoming)
  const writes = useRef(Promise.resolve())

  function change(value: string | null) {
    changed.current = true
    setCode(value)
    setReady(true)
    writes.current = writes.current
      .then(() => (value ? saveInvite(value) : deleteInvite()))
      .catch(() => {})
  }
  useEffect(() => {
    let active = true
    if (incoming) {
      writes.current = writes.current
        .then(() => saveInvite(incoming))
        .catch(() => {})
      return
    }
    void readInvite()
      .then(value => {
        if (active && !changed.current)
          setCode(value && /^pw_[A-Za-z0-9_-]{43}$/.test(value) ? value : null)
      })
      .catch(() => {})
      .finally(() => {
        if (active) setReady(true)
      })
    return () => {
      active = false
    }
    // Restore once; later deep links are handled below and cannot be overwritten by storage.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  useEffect(() => {
    if (incoming && incoming !== lastURL.current) change(incoming)
    lastURL.current = incoming
  }, [incoming])

  const preview = useQuery({
    queryKey: ['invite-preview', code],
    queryFn: () => teamPreviewInvite({ code: code! }),
    enabled: ready && !!code,
    retry: false,
    staleTime: 0,
    gcTime: 0,
    meta: { persist: false }
  })
  return {
    code,
    ready,
    details: preview.data,
    error: preview.error,
    pending: !!code && preview.isPending,
    clear: () => change(null),
    setCode: change
  }
}

export function PendingInviteProvider({ children }: { children: ReactNode }) {
  return <Context value={useInviteState()}>{children}</Context>
}
export function usePendingInvite() {
  const value = use(Context)
  if (!value) throw new Error('Приглашение используется вне провайдера')
  return value
}
