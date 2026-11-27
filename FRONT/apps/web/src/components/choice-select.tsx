'use client'

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from './ui/select'

export type Choice = { value: string; label: string; disabled?: boolean }

export function ChoiceSelect({
  value,
  onChange,
  options,
  label,
  className,
  disabled,
  id,
  ...accessibility
}: {
  value: string
  onChange: (value: string) => void
  options: readonly Choice[]
  label: string
  className?: string
  disabled?: boolean
  id?: string
  'aria-invalid'?: boolean
  'aria-describedby'?: string
}) {
  return (
    <Select
      value={value}
      onValueChange={onChange}
      disabled={disabled}
    >
      <SelectTrigger
        id={id}
        {...accessibility}
        aria-label={label}
        className={className}
      >
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {options.map(option => (
          <SelectItem
            key={option.value}
            value={option.value}
            disabled={option.disabled}
          >
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
