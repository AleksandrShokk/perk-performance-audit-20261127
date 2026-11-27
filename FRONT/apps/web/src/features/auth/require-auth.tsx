'use client'

import type { ReactNode } from 'react'

import { ErrorNotice, Loading } from '@/components/feedback'

import { NavigateTo } from './auth-entry'
import { useAuth } from './auth-provider'

export function RequireAuth({ children }: { children: ReactNode }) {
  const auth = useAuth()
  if (auth.status === 'loading')
    return (
      <div className='full-loading'>
        <Loading label='Открываем PERK' />
      </div>
    )
  if (auth.status === 'error')
    return (
      <div className='full-loading'>
        <ErrorNotice
          error={auth.error}
          onRetry={() => void auth.reload()}
        />
      </div>
    )
  if (auth.status === 'anonymous') return <NavigateTo href='/login' />
  if (!auth.user?.session_mfa_verified) return <NavigateTo href='/verify' />
  if (!auth.user.strong_factor_enabled) return <NavigateTo href='/phone' />
  return children
}
