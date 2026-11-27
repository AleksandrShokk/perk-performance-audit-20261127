import type { ReactNode } from 'react'

export function FormField({
  label,
  error,
  children
}: {
  label: string
  error?: string
  children: ReactNode
}) {
  return (
    <label className='field'>
      <span>{label}</span>
      {children}
      {error && (
        <span
          className='field-error'
          role='alert'
        >
          {error}
        </span>
      )}
    </label>
  )
}
