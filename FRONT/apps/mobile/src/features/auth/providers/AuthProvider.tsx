import { AuthMeResponse } from '@app/api/zod'
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
  getAuthMeQueryKey,
  getAuthMeQueryOptions,
  useAuthMe
} from '@app/api'

import { resetQueryCache } from '@/lib/queryClient'

import { session } from '../session/index'

/**
 * restoring    — читаем сохранённую сессию и пользователя;
 * signedOut    — нужен вход или регистрация;
 * secondFactor — пароль принят, нужен код второго фактора;
 * signedIn     — вход подтверждён;
 * offline      — сессия есть, но сервер недоступен и данных пользователя нет.
 */
export type AuthStatus =
  'restoring' | 'signedOut' | 'secondFactor' | 'signedIn' | 'offline'

type AuthContextValue = {
  status: AuthStatus
  user?: MeResponse
  /** Куда отправлен код при входе и какие способы подтверждения доступны. */
  secondFactor: SecondFactor | null
  startSession: (response: TokenResponse) => Promise<void>
  refreshUser: () => Promise<void>
  signOut: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const signingOut = useRef<Promise<void> | null>(null)
  const [hasSession, setHasSession] = useState<boolean | null>(null)
  const [secondFactor, setSecondFactor] = useState<SecondFactor | null>(null)
  const me = useAuthMe({
    query: {
      enabled: hasSession === true,
      retry: 1,
      select: value => AuthMeResponse.parse(value)
    }
  })

  useEffect(() => {
    let active = true
    session
      .restore()
      .then(restored => {
        if (active) setHasSession(restored)
      })
      .catch(() => {
        if (active) setHasSession(false)
      })

    const unsubscribe = session.onEnd(() => {
      setHasSession(false)
      setSecondFactor(null)
      return resetQueryCache()
    })
    return () => {
      active = false
      unsubscribe()
    }
  }, [])

  async function startSession(response: TokenResponse) {
    const started = await session.start(response)
    if (started !== session.generation) return
    await resetQueryCache()
    if (started !== session.generation) return
    setSecondFactor(response.second_factor ?? null)
    setHasSession(true)
    await queryClient.fetchQuery({ ...getAuthMeQueryOptions(), staleTime: 0 })
  }

  async function refreshUser() {
    await queryClient.refetchQueries({ queryKey: getAuthMeQueryKey() })
  }

  function signOut(): Promise<void> {
    if (signingOut.current) return signingOut.current
    const generation = session.generation
    const operation = (async () => {
      try {
        await authLogout()
      } catch {
        // Даже без сети удаляем сессию с устройства.
      } finally {
        // Поздний ответ выхода не должен завершить уже другую сессию.
        if (generation === session.generation) await session.end()
      }
    })().finally(() => {
      if (signingOut.current === operation) signingOut.current = null
    })
    signingOut.current = operation
    return operation
  }

  return (
    <AuthContext
      value={{
        status: resolveStatus(hasSession, me.data, me.isError),
        user: hasSession ? me.data : undefined,
        secondFactor,
        startSession,
        refreshUser,
        signOut
      }}
    >
      {children}
    </AuthContext>
  )
}

function resolveStatus(
  hasSession: boolean | null,
  user: MeResponse | undefined,
  failed: boolean
): AuthStatus {
  if (hasSession === null) return 'restoring'
  if (!hasSession) return 'signedOut'
  if (user) return user.session_mfa_verified ? 'signedIn' : 'secondFactor'
  return failed ? 'offline' : 'restoring'
}

export function useAuth() {
  const context = use(AuthContext)
  if (!context) throw new Error('useAuth вызван вне AuthProvider')
  return context
}
