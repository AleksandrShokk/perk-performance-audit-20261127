'use client'

import Link from 'next/link'
import { useState } from 'react'

import { authCancelFirstFactor } from '@app/api'

import { ErrorNotice } from '@/components/feedback'
import { Button } from '@/components/ui/button'

import { browserSession } from '@/lib/http'

export default function RecoverFactorPage() {
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState(false)
  const [error, setError] = useState<unknown>(null)
  async function cancel() {
    const token =
      new URLSearchParams(window.location.hash.slice(1)).get('code') ?? ''
    setBusy(true)
    setError(null)
    try {
      await authCancelFirstFactor({ token })
      browserSession.end()
      setDone(true)
      history.replaceState(null, '', location.pathname)
    } catch (error) {
      setError(error)
    } finally {
      setBusy(false)
    }
  }
  return (
    <main className='mx-auto max-w-lg space-y-6 p-8'>
      <h1>Защита аккаунта</h1>
      {done ? (
        <>
          <p>Подключение отменено. Все сессии завершены.</p>
          <Link href='/login'>Войти</Link>
        </>
      ) : (
        <>
          <p>
            Отменить подключение первого способа подтверждения? После отмены
            понадобится войти заново.
          </p>
          <Button
            disabled={busy}
            onClick={() => void cancel()}
          >
            Отменить подключение
          </Button>
        </>
      )}
      <ErrorNotice error={error} />
    </main>
  )
}
