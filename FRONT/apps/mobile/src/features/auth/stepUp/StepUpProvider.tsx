import {
  type ReactNode,
  createContext,
  use,
  useCallback,
  useEffect,
  useRef,
  useState
} from 'react'

import { session } from '@/features/auth/session'

import { useModalController } from '@/hooks/useModalController'

import { stepUpRequirement } from '@/lib/errors'

import { StepUpSheet } from './StepUpSheet'

export class StepUpCancelled extends Error {
  constructor() {
    super('Подтверждение отменено')
  }
}
type Pending = {
  strong: boolean
  resolve: () => void
  reject: (error: Error) => void
}
type Options = { beforePrompt?: () => Promise<void> }
type WithStepUp = <T>(action: () => Promise<T>, options?: Options) => Promise<T>
const StepUpContext = createContext<WithStepUp | null>(null)

/** Подтверждение открывается после закрытия формы, а действие продолжается после закрытия подтверждения. */
export function StepUpProvider({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState<Pending | null>(null)
  const active = useRef<Pending | null>(null)
  const busy = useRef(false)
  const closing = useRef(false)
  const mounted = useRef(true)
  const sessionVersion = useRef(0)
  const { visible, open, dismiss, onDismiss } = useModalController()

  const finish = useCallback(
    async (confirmed: boolean) => {
      const request = active.current
      if (!request || closing.current) return
      closing.current = true
      await dismiss()
      if (active.current !== request) return
      active.current = null
      closing.current = false
      if (mounted.current) setPending(null)
      if (confirmed) request.resolve()
      else request.reject(new StepUpCancelled())
    },
    [dismiss]
  )

  useEffect(() => {
    mounted.current = true
    const unsubscribe = session.onEnd(() => {
      sessionVersion.current += 1
      void finish(false)
    })
    return () => {
      mounted.current = false
      sessionVersion.current += 1
      active.current?.reject(new StepUpCancelled())
      active.current = null
      unsubscribe()
    }
  }, [finish])

  async function withStepUp<T>(
    action: () => Promise<T>,
    options?: Options
  ): Promise<T> {
    const version = sessionVersion.current
    try {
      return await action()
    } catch (error) {
      const requirement = stepUpRequirement(error)
      if (!requirement) throw error
      if (busy.current) throw new StepUpCancelled()
      busy.current = true
      try {
        if (!mounted.current || version !== sessionVersion.current)
          throw new StepUpCancelled()
        await options?.beforePrompt?.()
        if (!mounted.current || version !== sessionVersion.current)
          throw new StepUpCancelled()
        await new Promise<void>((resolve, reject) => {
          const request = { strong: requirement.strong, resolve, reject }
          active.current = request
          setPending(request)
          void open()
        })
        return await action()
      } finally {
        busy.current = false
      }
    }
  }
  return (
    <StepUpContext value={withStepUp}>
      {children}
      {pending && (
        <StepUpSheet
          strong={pending.strong}
          visible={visible}
          onDismiss={onDismiss}
          onConfirmed={() => finish(true)}
          onCancel={() => void finish(false)}
        />
      )}
    </StepUpContext>
  )
}
export function useStepUp() {
  const context = use(StepUpContext)
  if (!context) throw new Error('useStepUp вызван вне StepUpProvider')
  return context
}
