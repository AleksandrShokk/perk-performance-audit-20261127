'use client'

import { ChevronLeft, ChevronRight } from 'lucide-react'

import { ChoiceSelect } from './choice-select'
import { Button } from './ui/button'

export function TablePagination({
  page,
  pageSize,
  total,
  onPage,
  onPageSize,
  busy = false,
  label = 'таблицы'
}: {
  page: number
  pageSize: number
  total: number
  onPage: (page: number) => void
  onPageSize?: (size: number) => void
  busy?: boolean
  label?: string
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize))
  const current = Math.min(page, pages - 1)
  const first = Math.max(0, Math.min(current - 3, pages - 7))
  const numbers = Array.from(
    { length: Math.min(7, pages) },
    (_, index) => first + index
  )
  return (
    <nav
      className='table-pagination'
      aria-label={`Страницы ${label}`}
    >
      {onPageSize && (
        <ChoiceSelect
          label={`Показывать строк ${label}`}
          value={String(pageSize)}
          onChange={value => onPageSize(Number(value))}
          disabled={busy}
          options={[25, 50, 100].map(value => ({
            value: String(value),
            label: `${value} на странице`
          }))}
        />
      )}
      <div className='page-numbers'>
        <Button
          variant='ghost'
          size='icon-sm'
          aria-label={`Предыдущая страница ${label}`}
          disabled={!current || busy}
          onClick={() => onPage(current - 1)}
        >
          <ChevronLeft size={16} />
        </Button>
        {first > 0 && (
          <>
            <Button
              variant='ghost'
              size='sm'
              disabled={busy}
              onClick={() => onPage(0)}
            >
              1
            </Button>
            <span aria-hidden>…</span>
          </>
        )}
        {numbers.map(number => (
          <Button
            key={number}
            size='sm'
            variant={number === current ? 'secondary' : 'ghost'}
            aria-label={`Страница ${number + 1} ${label}`}
            aria-current={number === current ? 'page' : undefined}
            disabled={busy}
            onClick={() => onPage(number)}
          >
            {number + 1}
          </Button>
        ))}
        {first + numbers.length < pages && (
          <>
            <span aria-hidden>…</span>
            <Button
              variant='ghost'
              size='sm'
              disabled={busy}
              onClick={() => onPage(pages - 1)}
            >
              {pages}
            </Button>
          </>
        )}
        <Button
          variant='ghost'
          size='icon-sm'
          aria-label={`Следующая страница ${label}`}
          disabled={current + 1 >= pages || busy}
          onClick={() => onPage(current + 1)}
        >
          <ChevronRight size={16} />
        </Button>
      </div>
    </nav>
  )
}
