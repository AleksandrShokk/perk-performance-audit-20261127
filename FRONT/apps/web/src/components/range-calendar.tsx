'use client'

import {
  type DateRange,
  HISTORY_START,
  lastDays,
  toISODate
} from '@app/analytics/dates'
import {
  addDays,
  addMonths,
  differenceInCalendarDays,
  isValid,
  parseISO,
  startOfMonth,
  startOfWeek
} from 'date-fns'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { useState } from 'react'

import { ChoiceSelect } from './choice-select'
import { Button } from './ui/button'

const months = [
  'Январь',
  'Февраль',
  'Март',
  'Апрель',
  'Май',
  'Июнь',
  'Июль',
  'Август',
  'Сентябрь',
  'Октябрь',
  'Ноябрь',
  'Декабрь'
]
export function displayDate(day: string) {
  return /^\d{4}-\d{2}-\d{2}$/.test(day)
    ? day.split('-').reverse().join('.')
    : day
}
export function inputDate(value: string) {
  return /^\d{2}\.\d{2}\.\d{4}$/.test(value)
    ? value.split('.').reverse().join('-')
    : value
}

export function RangeCalendar({
  value,
  onChange,
  maxDays,
  minDate = HISTORY_START
}: {
  value: DateRange
  onChange: (value: DateRange) => void
  maxDays: number
  minDate?: string
}) {
  const last = lastDays(1).date_to
  const [month, setMonth] = useState(() =>
    startOfMonth(parseISO(value.date_to || last))
  )
  const [active, setActive] = useState<'date_from' | 'date_to'>('date_from')
  const firstMonth = minDate.slice(0, 7) + '-01'
  const setVisibleMonth = (date: Date) => {
    const selected = toISODate(startOfMonth(date))
    setMonth(
      parseISO(
        selected < firstMonth
          ? firstMonth
          : selected.slice(0, 7) > last.slice(0, 7)
            ? last.slice(0, 7) + '-01'
            : selected
      )
    )
  }
  const first = startOfWeek(startOfMonth(month), { weekStartsOn: 1 })
  const count =
    differenceInCalendarDays(
      parseISO(value.date_to),
      parseISO(value.date_from)
    ) + 1
  const from =
    /^\d{4}-\d{2}-\d{2}$/.test(value.date_from) &&
    isValid(parseISO(value.date_from))
      ? value.date_from
      : last
  const boundary =
    active === 'date_to'
      ? toISODate(addDays(parseISO(from), maxDays - 1))
      : last
  const pick = (day: string) => {
    if (active === 'date_from') {
      const end = toISODate(addDays(parseISO(day), maxDays - 1))
      onChange({
        date_from: day,
        date_to:
          value.date_to < day
            ? day
            : value.date_to > end
              ? end > last
                ? last
                : end
              : value.date_to
      })
      setActive('date_to')
    } else onChange({ ...value, date_to: day })
  }
  return (
    <div className='range-calendar'>
      <div className='date-fields'>
        {(
          [
            ['date_from', 'С'],
            ['date_to', 'По']
          ] as const
        ).map(([key, label]) => (
          <label
            className='field'
            key={key}
          >
            <span>{label}</span>
            <input
              className={`calendar-date-input ${active === key ? 'active' : ''}`}
              aria-label={label}
              value={displayDate(value[key])}
              placeholder='ДД.ММ.ГГГГ'
              inputMode='numeric'
              aria-invalid={value[key] < minDate || value[key] > last}
              onFocus={() => setActive(key)}
              onChange={event =>
                onChange({ ...value, [key]: inputDate(event.target.value) })
              }
            />
          </label>
        ))}
      </div>
      <div className='calendar-navigation'>
        <Button
          type='button'
          variant='ghost'
          size='icon-sm'
          aria-label='Предыдущий месяц'
          disabled={toISODate(month) <= firstMonth}
          onClick={() => setMonth(addMonths(month, -1))}
        >
          <ChevronLeft size={16} />
        </Button>
        <ChoiceSelect
          label='Месяц'
          value={String(month.getMonth())}
          options={months.map((label, index) => ({
            value: String(index),
            label,
            disabled:
              new Date(month.getFullYear(), index + 1, 0) < parseISO(minDate) ||
              new Date(month.getFullYear(), index, 1) > parseISO(last)
          }))}
          onChange={value =>
            setVisibleMonth(new Date(month.getFullYear(), Number(value), 1))
          }
        />
        <ChoiceSelect
          label='Год'
          value={String(month.getFullYear())}
          options={Array.from(
            {
              length: Number(last.slice(0, 4)) - Number(minDate.slice(0, 4)) + 1
            },
            (_, index) => ({
              value: String(Number(minDate.slice(0, 4)) + index),
              label: String(Number(minDate.slice(0, 4)) + index)
            })
          )}
          onChange={value =>
            setVisibleMonth(new Date(Number(value), month.getMonth(), 1))
          }
        />
        <Button
          type='button'
          variant='ghost'
          size='icon-sm'
          aria-label='Следующий месяц'
          disabled={toISODate(month).slice(0, 7) >= last.slice(0, 7)}
          onClick={() => setMonth(addMonths(month, 1))}
        >
          <ChevronRight size={16} />
        </Button>
      </div>
      <div className='calendar-weekdays'>
        {['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'].map(day => (
          <span key={day}>{day}</span>
        ))}
      </div>
      <div
        className='calendar-grid'
        role='group'
        aria-label='Дни периода'
      >
        {Array.from({ length: 42 }, (_, index) => {
          const date = addDays(first, index),
            day = toISODate(date)
          const disabled =
            day < minDate ||
            day > last ||
            (active === 'date_to' && (day < value.date_from || day > boundary))
          const selected = day >= value.date_from && day <= value.date_to
          return (
            <button
              type='button'
              key={day}
              aria-label={displayDate(day)}
              aria-pressed={selected}
              disabled={disabled}
              className={`${date.getMonth() !== month.getMonth() ? 'outside' : ''} ${selected ? 'in-range' : ''} ${day === value.date_from || day === value.date_to ? 'range-edge' : ''}`}
              onClick={() => pick(day)}
            >
              {date.getDate()}
            </button>
          )
        })}
      </div>
      <div
        className='calendar-count'
        role='status'
      >
        {Number.isFinite(count) && count > 0
          ? `${count} дней · максимум ${maxDays}`
          : `Максимум ${maxDays} дней`}
      </div>
    </div>
  )
}
