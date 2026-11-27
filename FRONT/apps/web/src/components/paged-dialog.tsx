'use client'

import { useInfiniteQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import { Empty, ErrorNotice, Loading } from './feedback'
import { Button } from './ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from './ui/dialog'

type Page<T> = { items: T[]; count: number; limit: number; offset: number }
type Props<T> = {
  open: boolean
  onClose: () => void
  title: string
  description: string
  queryKey: readonly unknown[]
  load: (offset: number, signal: AbortSignal) => Promise<Page<T>>
  render: (row: T) => ReactNode
  rowKey: (row: T) => string
}
/** One pagination mechanism for inventory, recommendations and formed supplies. */
export function PagedDialog<T>({
  open,
  onClose,
  title,
  description,
  queryKey,
  load,
  render,
  rowKey
}: Props<T>) {
  const query = useInfiniteQuery({
    queryKey,
    queryFn: ({ pageParam, signal }) => load(pageParam, signal),
    initialPageParam: 0,
    getNextPageParam: last =>
      last.offset + last.limit < last.count
        ? last.offset + last.limit
        : undefined,
    enabled: open
  })
  const rows = query.data?.pages.flatMap(page => page.items) ?? []
  return (
    <Dialog
      open={open}
      onOpenChange={value => {
        if (!value) onClose()
      }}
    >
      <DialogContent className='report-dialog'>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <div className='dialog-scroll'>
          <ErrorNotice
            error={query.error}
            onRetry={() => void query.refetch()}
          />
          {query.isPending ? (
            <Loading />
          ) : rows.length ? (
            <div className='detail-list'>
              {rows.map(row => (
                <div
                  className='detail-row'
                  key={rowKey(row)}
                >
                  {render(row)}
                </div>
              ))}
            </div>
          ) : (
            <Empty title='Пока ничего нет' />
          )}
          {query.hasNextPage && (
            <Button
              variant='secondary'
              className='load-more'
              disabled={query.isFetchingNextPage}
              onClick={() => void query.fetchNextPage()}
            >
              {query.isFetchingNextPage ? 'Загружаем…' : 'Показать ещё'}
            </Button>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
