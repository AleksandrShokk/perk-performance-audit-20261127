import { AlertCircle, LoaderCircle } from 'lucide-react'

import { Button } from '@/components/ui/button'

import { errorMessage } from '@/lib/errors'

export function ErrorNotice({
  error,
  onRetry
}: {
  error: unknown
  onRetry?: () => void
}) {
  if (!error) return null
  return (
    <div
      role='alert'
      className='error-notice'
    >
      <AlertCircle
        size={17}
        aria-hidden
      />
      <span>{errorMessage(error)}</span>
      {onRetry && (
        <Button
          variant='ghost'
          size='sm'
          onClick={onRetry}
        >
          Повторить
        </Button>
      )}
    </div>
  )
}
export function Loading({ label = 'Загружаем данные' }: { label?: string }) {
  return (
    <div
      className='loading-state'
      role='status'
    >
      <LoaderCircle
        className='animate-spin'
        size={22}
      />
      <span>{label}</span>
    </div>
  )
}
export function Empty({
  title,
  children
}: {
  title: string
  children?: React.ReactNode
}) {
  return (
    <div className='empty-state'>
      <strong>{title}</strong>
      {children && <div>{children}</div>}
    </div>
  )
}
