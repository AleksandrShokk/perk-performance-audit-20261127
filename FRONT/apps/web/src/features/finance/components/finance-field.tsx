'use client'

import { type ReactElement, cloneElement, useId } from 'react'

type Control = {
  id?: string
  'aria-invalid'?: boolean
  'aria-describedby'?: string
}
export function FinanceField({
  label,
  error,
  children
}: {
  label: string
  error?: string
  children: ReactElement<Control>
}) {
  const id = useId()
  return (
    <div className='field'>
      <label htmlFor={id}>{label}</label>
      {cloneElement(children, {
        id,
        'aria-invalid': !!error,
        'aria-describedby': error ? `${id}-error` : undefined
      })}
      {error && (
        <span
          id={`${id}-error`}
          className='field-error'
          role='alert'
        >
          {error}
        </span>
      )}
    </div>
  )
}
