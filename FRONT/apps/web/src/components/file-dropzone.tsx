'use client'

import { Upload } from 'lucide-react'
import { useId, useState } from 'react'

export function FileDropzone({
  onFile,
  disabled,
  label = 'Перетащите XLSX или выберите файл'
}: {
  onFile: (file: File) => void
  disabled?: boolean
  label?: string
}) {
  const id = useId()
  const [over, setOver] = useState(false)
  const [name, setName] = useState('')
  const select = (file?: File) => {
    if (!file || disabled) return
    setName(file.name)
    onFile(file)
  }
  return (
    <label
      htmlFor={id}
      className={`file-dropzone ${over ? 'file-dropzone-over' : ''}`}
      aria-disabled={disabled}
      onDragOver={event => {
        event.preventDefault()
        if (!disabled) setOver(true)
      }}
      onDragLeave={() => setOver(false)}
      onDrop={event => {
        event.preventDefault()
        setOver(false)
        select(event.dataTransfer.files[0])
      }}
    >
      <Upload
        size={20}
        aria-hidden
      />
      <span>{name || 'Перетащите XLSX или выберите файл'}</span>
      <input
        id={id}
        aria-label={label}
        type='file'
        accept='.xlsx'
        disabled={disabled}
        className='sr-only'
        onChange={event => {
          select(event.target.files?.[0])
          event.target.value = ''
        }}
      />
    </label>
  )
}
