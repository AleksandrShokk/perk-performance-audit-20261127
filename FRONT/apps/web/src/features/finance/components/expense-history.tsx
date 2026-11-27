'use client'

import { useInfiniteQuery, useMutation } from '@tanstack/react-query'
import { Trash2 } from 'lucide-react'
import { useState } from 'react'

import { expensesDelete, expensesList } from '@app/api'

import { Empty, ErrorNotice, Loading } from '@/components/feedback'
import { Button } from '@/components/ui/button'

import { useAuth } from '@/features/auth/auth-provider'
import { useWorkspace } from '@/features/workspace/workspace-provider'

import { financeMoney } from '../model/finance-format'
import { expenseCategories } from '../model/forms'

import type { StoreFormProps } from './expense-form'

export function ExpenseHistory({
  workspaceId,
  storeId,
  onSaved
}: StoreFormProps) {
  const { user } = useAuth()
  const scope = useWorkspace()
  const [deleting, setDeleting] = useState<string>()
  const history = useInfiniteQuery({
    queryKey: [
      'user',
      user?.id,
      workspaceId,
      'finance',
      scope.accessKey,
      storeId,
      'expenses'
    ],
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) =>
      expensesList(
        workspaceId,
        storeId,
        { offset: pageParam, limit: 50 },
        { signal }
      ),
    getNextPageParam: (last, _pages, offset) =>
      last.length === 50 && offset < 50000 ? offset + 50 : undefined
  })
  const remove = useMutation({
    mutationFn: (id: string) => expensesDelete(workspaceId, storeId, id),
    onSuccess: async () => {
      setDeleting(undefined)
      await onSaved()
    }
  })
  const rows = history.data?.pages.flat() ?? []
  return (
    <div className='form-stack'>
      <ErrorNotice
        error={history.error ?? remove.error}
        onRetry={history.error ? () => void history.refetch() : undefined}
      />
      {history.isPending ? (
        <Loading />
      ) : !rows.length ? (
        <Empty title='Внешних расходов пока нет' />
      ) : (
        <div className='table-scroll'>
          <table className='data-table expense-history'>
            <thead>
              <tr>
                <th>Дата</th>
                <th>Расход</th>
                <th>Сумма</th>
                {scope.can('expenses.write') && <th></th>}
              </tr>
            </thead>
            <tbody>
              {rows.map(row => (
                <tr key={row.id}>
                  <td>
                    {new Intl.DateTimeFormat('ru-RU').format(
                      new Date(`${row.expense_date}T12:00:00`)
                    )}
                  </td>
                  <td>
                    <strong>{row.comment}</strong>
                    <small>
                      {row.custom_category ||
                        expenseCategories.find(
                          ([key]) => key === row.category
                        )?.[1] ||
                        'Прочее'}
                    </small>
                  </td>
                  <td>{financeMoney(row.amount, row.currency)}</td>
                  {scope.can('expenses.write') && (
                    <td>
                      {deleting === row.id ? (
                        <span className='delete-confirm'>
                          <Button
                            size='sm'
                            variant='destructive'
                            disabled={remove.isPending}
                            onClick={() => remove.mutate(row.id)}
                          >
                            Удалить
                          </Button>
                          <Button
                            size='sm'
                            variant='ghost'
                            onClick={() => setDeleting(undefined)}
                          >
                            Отмена
                          </Button>
                        </span>
                      ) : (
                        <Button
                          variant='ghost'
                          size='icon-sm'
                          aria-label={`Удалить расход «${row.comment}»`}
                          onClick={() => setDeleting(row.id)}
                        >
                          <Trash2 size={15} />
                        </Button>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {history.hasNextPage && (
        <Button
          variant='outline'
          disabled={history.isFetchingNextPage}
          onClick={() => void history.fetchNextPage()}
        >
          {history.isFetchingNextPage ? 'Загружаем…' : 'Показать ещё'}
        </Button>
      )}
    </div>
  )
}
