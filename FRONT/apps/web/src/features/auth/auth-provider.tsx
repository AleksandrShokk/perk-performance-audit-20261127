'use client'

import { useQueryClient } from '@tanstack/react-query'
import {
  type ReactNode,
  createContext,
  use,
  useEffect,
  useRef,
  useState
} from 'react'

import {
  type MeResponse,
  type SecondFactor,
  type TokenResponse,
  authLogout,
  authLogoutAll,
  authMe
} from '@app/api'

import { statusOf } from '@/lib/errors'
import { browserSession, readCsrf } from '@/lib/http'

type AuthState = {
  status: 'loading' | 'anonymous' | 'authenticated' | 'error'
  user?: MeResponse
  error?: unknown
}
type Auth = AuthState & {
  secondFactor: SecondFactor | null
  accept: (token: TokenResponse) => Promise<void>
  reload: () => Promise<void>
  signOut: () => Promise<void>
  signOutAll: () => Promise<void>
}
const Context = createContext<Auth | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const client = useQueryClient()
  const [state, setState] = useState<AuthState>({ status: 'loading' })
  const [secondFactor, setSecondFactor] = useState<SecondFactor | null>(null)
  const pendingLogout = useRef<Promise<void> | null>(null)
  async function reload() {
    const started = browserSession.epoch
    try {
      const user = await authMe()
      if (started === browserSession.epoch)
        setState({ status: 'authenticated', user })
    } catch (error) {
      if (started !== browserSession.epoch) return
      setState(
        statusOf(error) === 401
          ? { status: 'anonymous' }
          : { status: 'error', error }
      )
    }
  }
  useEffect(() => {
    browserSession.install()
    const unsubscribe = browserSession.subscribe(() => {
      void client.cancelQueries()
      client.clear()
      setSecondFactor(null)
      setState({ status: 'anonymous' })
    })
    let active = true
    // Defer the first request so Strict Mode's trial mount never races a refresh rotation.
    void Promise.resolve().then(async () => {
      if (!active) return
      if (!readCsrf()) {
        setState({ status: 'anonymous' })
        return
      }
      await reload()
    })
    return () => {
      active = false
      unsubscribe()
    }
    // The transport and query client live for the lifetime of this browser application.
  }, [client])

  async function accept(token: TokenResponse) {
    if (!token.csrf_token)
      throw new Error('Не удалось сохранить браузерную сессию.')
    browserSession.advance()
    await client.cancelQueries()
    client.clear()
    setSecondFactor(token.second_factor ?? null)
    setState({ status: 'loading' })
    await reload()
  }
  function signOut(all = false) {
    if (pendingLogout.current) return pendingLogout.current
    const operation = (async () => {
      await client.cancelQueries()
      // The backend revokes the session and removes the HttpOnly cookies.
      if (all) await authLogoutAll()
      else await authLogout()
      browserSession.end()
    })().finally(() => {
      pendingLogout.current = null
    })
    pendingLogout.current = operation
    return operation
  }
  return (
    <Context
      value={{
        ...state,
        secondFactor,
        accept,
        reload,
        signOut: () => signOut(),
        signOutAll: () => signOut(true)
      }}
    >
      {children}
    </Context>
  )
}
export function useAuth() {
  const value = use(Context)
  if (!value) throw new Error('AuthProvider отсутствует')
  return value
}
