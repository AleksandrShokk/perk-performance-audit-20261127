import { formatNumber } from '@app/analytics/format'
import { ChevronLeft, ChevronRight } from 'lucide-react'

import { Button } from '@/components/ui/button'

import { supplyPageSize } from '../hooks/use-supplies'

export function SupplyPagination({
  page,
  count,
  busy,
  onPage
}: {
  page: number
  count: number
  busy: boolean
  onPage: (page: number) => void
}) {
  return (
    <div className='table-footer'>
      <span>
        {count
          ? `${formatNumber(page * supplyPageSize + 1)}–${formatNumber(Math.min((page + 1) * supplyPageSize, count))} из ${formatNumber(count)}`
          : '0 позиций'}
      </span>
      <div>
        <Button
          variant='ghost'
          size='icon-sm'
          aria-label='Предыдущая страница поставок'
          disabled={page === 0 || busy}
          onClick={() => onPage(page - 1)}
        >
          <ChevronLeft size={16} />
        </Button>
        <span>{page + 1}</span>
        <Button
          variant='ghost'
          size='icon-sm'
          aria-label='Следующая страница поставок'
          disabled={(page + 1) * supplyPageSize >= count || busy}
          onClick={() => onPage(page + 1)}
        >
          <ChevronRight size={16} />
        </Button>
      </div>
    </div>
  )
}
