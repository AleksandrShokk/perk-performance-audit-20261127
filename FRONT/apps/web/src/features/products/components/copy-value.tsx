'use client'

import { Check, Copy } from 'lucide-react'
import { useState } from 'react'

export function CopyValue({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false)
  const [failed, setFailed] = useState(false)
  return (
    <span className='copy-field'>
      <button
        aria-label={`Скопировать ${label}`}
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(value)
            setCopied(true)
            setFailed(false)
          } catch {
            setFailed(true)
          }
        }}
      >
        <span>{value}</span>
        {copied ? <Check size={14} /> : <Copy size={14} />}
      </button>
      {failed && <small role='alert'>Не удалось скопировать</small>}
    </span>
  )
}
