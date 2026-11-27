'use client'

import { useMutation } from '@tanstack/react-query'
import { isAxiosError } from 'axios'
import Link from 'next/link'
import {
  type ReactNode,
  createContext,
  use,
  useEffect,
  useRef,
  useState
} from 'react'

import { authStepUpSend, authStepUpVerify } from '@app/api'

import { ErrorNotice } from '@/components/feedback'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog'

import { useWorkspace } from '@/features/workspace/workspace-provider'

import { browserSession } from '@/lib/http'

import { useAuth } from './auth-provider'
import { CodeForm } from './code-form'

export class StepUpCancelled extends Error {
  constructor() {
    super('Подтверждение отменено')
  }
}
export function confirmationRequired(error: unknown) {
  if (!isAxiosError(error) || error.response?.status !== 403) return null
  const code =
    error.response.data?.detail?.code ?? error.response.data?.error?.code
  return code === 'strong_step_up_required'
    ? 'strong'
    : code === 'step_up_required'
      ? 'recent'
      : null
}
type Confirm = <T>(action: () => Promise<T>, signal?: AbortSignal) => Promise<T>
type Pending = {
  id: string
  strong: boolean
  resolve: () => void
  reject: (error: Error) => void
  cleanup: () => void
}
const Context = createContext<Confirm | null>(null)
export function StepUpProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth(),
    scope = useWorkspace()
  return (
    <ConfirmationScope key={`${user?.id}:${scope.accessKey}`}>
      {children}
    </ConfirmationScope>
  )
}
function ConfirmationScope({ children }: { children: ReactNode }) {
  const active = useRef<Pending | null>(null)
  const [pending, setPending] = useState<Pending | null>(null)
  function finish(confirmed: boolean, id = active.current?.id) {
    const request = active.current
    if (!request || request.id !== id) return
    active.current = null
    request.cleanup()
    setPending(null)
    if (confirmed) request.resolve()
    else request.reject(new StepUpCancelled())
  }
  useEffect(
    () => () => {
      const request = active.current
      active.current = null
      request?.cleanup()
      request?.reject(new StepUpCancelled())
    },
    []
  )
  async function confirm<T>(
    action: () => Promise<T>,
    signal?: AbortSignal
  ): Promise<T> {
    const epoch = browserSession.epoch
    if (signal?.aborted) throw new StepUpCancelled()
    try {
      return await action()
    } catch (error) {
      const requirement = confirmationRequired(error)
      if (!requirement) throw error
      if (active.current || signal?.aborted || epoch !== browserSession.epoch)
        throw new StepUpCancelled()
      await new Promise<void>((resolve, reject) => {
        const cancel = () => finish(false)
        const request: Pending = {
          id: crypto.randomUUID(),
          strong: requirement === 'strong',
          resolve,
          reject,
          cleanup: () => signal?.removeEventListener('abort', cancel)
        }
        signal?.addEventListener('abort', cancel, { once: true })
        active.current = request
        setPending(request)
      })
      if (signal?.aborted || epoch !== browserSession.epoch)
        throw new StepUpCancelled()
      return await action()
    }
  }
  return (
    <Context value={confirm}>
      {children}
      {pending && (
        <ConfirmationDialog
          key={pending.id}
          strong={pending.strong}
          onCancel={() => finish(false, pending.id)}
          onConfirmed={() => finish(true, pending.id)}
        />
      )}
    </Context>
  )
}
function ConfirmationDialog({
  strong,
  onCancel,
  onConfirmed
}: {
  strong: boolean
  onCancel: () => void
  onConfirmed: () => void
}) {
  const { user } = useAuth()
  const send = useMutation({ mutationFn: () => authStepUpSend({}), gcTime: 0 })
  return (
    <Dialog
      open
      onOpenChange={open => {
        if (!open) onCancel()
      }}
    >
      <DialogContent className='max-w-md'>
        <DialogHeader>
          <DialogTitle>Подтвердите действие</DialogTitle>
          <DialogDescription>
            {user?.totp_enabled
              ? 'Введите код из аутентификатора.'
              : 'Введите код из вашего канала подтверждения.'}
          </DialogDescription>
        </DialogHeader>
        {strong && !user?.strong_factor_enabled ? (
          <Link
            href='/phone'
            className='text-link'
            onClick={onCancel}
          >
            Привязать телефон
          </Link>
        ) : user?.totp_enabled || send.data ? (
          <CodeForm
            destination={send.data?.destination}
            seconds={send.data?.resend_after}
            recovery={!!user?.strong_factor_enabled}
            onVerify={async code => {
              await authStepUpVerify({ code })
              onConfirmed()
            }}
            onResend={
              user?.totp_enabled
                ? undefined
                : async () => (await send.mutateAsync()).resend_after
            }
          />
        ) : (
          <Button
            disabled={send.isPending}
            onClick={() => send.mutate()}
          >
            {send.isPending ? 'Отправляем…' : 'Получить код'}
          </Button>
        )}
        <ErrorNotice error={send.error} />
        <Button
          variant='ghost'
          onClick={onCancel}
        >
          Отмена
        </Button>
      </DialogContent>
    </Dialog>
  )
}
export function useStepUp() {
  const value = use(Context)
  if (!value) throw new Error('Нет провайдера подтверждения')
  return value
}
