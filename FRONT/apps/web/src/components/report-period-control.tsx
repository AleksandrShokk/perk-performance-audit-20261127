'use client'

import { type DateRange, HISTORY_START } from '@app/analytics/dates'
import { formatDateRange } from '@app/analytics/format'
import { rangeError, resolvePeriod } from '@app/analytics/periods'
import { CalendarDays } from 'lucide-react'
import { useState } from 'react'

import { RangeCalendar, displayDate } from './range-calendar'
import { Button } from './ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from './ui/dialog'

export function ReportPeriodControl<T extends number>({
  value,
  onChange,
  options,
  maxDays = 1100,
  minDate = HISTORY_START,
  disabled = false
}: {
  value: T | DateRange
  onChange: (period: T | DateRange) => void
  options: readonly T[]
  maxDays?: number
  minDate?: string
  disabled?: boolean
}) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState<DateRange>(() => resolvePeriod(value))
  const [error, setError] = useState<string>()
  return (
    <div className='period-controls'>
      <div
        className='period-segments'
        aria-label='Период отчёта'
      >
        {options.map(days => (
          <button
            key={days}
            aria-pressed={value === days}
            disabled={disabled || resolvePeriod(days).date_from < minDate}
            onClick={() => onChange(days)}
          >
            {days} дней
          </button>
        ))}
      </div>
      <Button
        variant='outline'
        disabled={disabled}
        className={
          typeof value === 'object' ? 'custom-period active' : 'custom-period'
        }
        onClick={() => {
          setDraft(resolvePeriod(value))
          setError(undefined)
          setOpen(true)
        }}
      >
        <CalendarDays size={16} />
        {typeof value === 'object'
          ? formatDateRange(value.date_from, value.date_to)
          : 'Свой период'}
      </Button>
      <Dialog
        open={open}
        onOpenChange={setOpen}
      >
        <DialogContent
          className='range-dialog'
          aria-describedby={undefined}
        >
          <DialogHeader>
            <DialogTitle>Свой период</DialogTitle>
          </DialogHeader>
          <form
            className='form-stack'
            onSubmit={event => {
              event.preventDefault()
              const issue =
                rangeError(draft, maxDays) ??
                (draft.date_from < minDate
                  ? `История доступна с ${displayDate(minDate)}`
                  : undefined)
              setError(issue)
              if (!issue) {
                onChange(draft)
                setOpen(false)
              }
            }}
          >
            <RangeCalendar
              value={draft}
              onChange={value => {
                setDraft(value)
                setError(undefined)
              }}
              maxDays={maxDays}
              minDate={minDate}
            />
            {error && (
              <p
                role='alert'
                className='field-error'
              >
                {error}
              </p>
            )}
            <Button type='submit'>Применить</Button>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}
