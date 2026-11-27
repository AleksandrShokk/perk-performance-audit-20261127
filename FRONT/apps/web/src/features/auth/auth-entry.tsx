'use client'

import { useRouter } from 'next/navigation'
import { useEffect } from 'react'

import { ErrorNotice, Loading } from '@/components/feedback'

import { useAuth } from './auth-provider'
import { AuthScreen } from './auth-screen'
import { PhoneEnrollment, VerificationScreen } from './verification-screen'

export function NavigateTo({ href }: { href: string }) {
  const router = useRouter()
  useEffect(() => router.replace(href), [href, router])
  return (
    <div className='full-loading'>
      <Loading label='Открываем PERK' />
    </div>
  )
}
export function AuthEntry({
  mode
}: {
  mode: 'login' | 'register' | 'forgot' | 'verify' | 'phone'
}) {
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
  if (auth.status === 'anonymous')
    return mode === 'verify' || mode === 'phone' ? (
      <NavigateTo href='/login' />
    ) : (
      <AuthScreen mode={mode} />
    )
  if (!auth.user?.session_mfa_verified)
    return mode === 'verify' ? (
      <VerificationScreen />
    ) : (
      <NavigateTo href='/verify' />
    )
  if (mode === 'phone') return <PhoneEnrollment />
  if (!auth.user.strong_factor_enabled)
    return <NavigateTo href='/phone' />
  return <NavigateTo href='/' />
}
