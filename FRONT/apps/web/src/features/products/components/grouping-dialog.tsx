'use client'

import { useQuery } from '@tanstack/react-query'
import { useDeferredValue, useState } from 'react'

import {
  type ProductItem,
  type ProductModel,
  catalogGroupSave,
  catalogModels
} from '@app/api'

import { ChoiceSelect } from '@/components/choice-select'
import { ErrorNotice, Loading } from '@/components/feedback'
import { TablePagination } from '@/components/table-pagination'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'

import { useAuth } from '@/features/auth/auth-provider'
import { useWorkspace } from '@/features/workspace/workspace-provider'

import { useProtectedAction } from '@/hooks/use-protected-action'

const article = (product: ProductItem) =>
  product.marketplace === 'ozon' ? product.external_id : product.nm_id
export function GroupingDialog({
  model,
  onClose,
  onSaved
}: {
  model?: ProductModel
  onClose: () => void
  onSaved: () => void
}) {
  const scope = useWorkspace(),
    { user } = useAuth()
  const [sid, setSid] = useState(
    model?.store_id ?? scope.store?.id ?? scope.stores[0]?.id ?? ''
  )
  const [search, setSearch] = useState(''),
    q = useDeferredValue(search)
  const [page, setPage] = useState(0),
    [title, setTitle] = useState(model?.title ?? '')
  const [chosen, setChosen] = useState<Map<string, string>>(
    () =>
      new Map(
        model?.products.map(p => [
          article(p) || '',
          p.vendor_code || p.title
        ]) ?? []
      )
  )
  const [action, setAction] = useState<'merge' | 'split' | 'reset'>('merge')
  const query = useQuery({
    queryKey: [
      'user',
      user?.id,
      scope.accessKey,
      'grouping-catalog',
      sid,
      q,
      page
    ],
    queryFn: ({ signal }) =>
      catalogModels(
        scope.workspace!.id,
        { store_id: sid, q, limit: 25, offset: page * 25 },
        { signal }
      ),
    enabled: !!sid
  })
  const save = useProtectedAction(
    signal =>
      catalogGroupSave(
        scope.workspace!.id,
        sid,
        { action, articles: [...chosen.keys()], title },
        { signal }
      ),
    () => {
      onSaved()
      onClose()
    }
  )
  const toggle = (p: ProductItem) =>
    setChosen(previous => {
      const next = new Map(previous),
        id = article(p)
      if (id) {
        if (next.has(id)) next.delete(id)
        else next.set(id, p.vendor_code || p.title)
      }
      return next
    })
  return (
    <Dialog
      open
      onOpenChange={open => {
        if (!open) onClose()
      }}
    >
      <DialogContent
        className='catalog-import-dialog'
        aria-describedby={undefined}
      >
        <DialogHeader>
          <DialogTitle>Объединение карточек</DialogTitle>
        </DialogHeader>
        <div className='form-stack'>
          <ChoiceSelect
            label='Кабинет для объединения'
            value={sid}
            disabled={save.isPending}
            onChange={value => {
              setSid(value)
              setChosen(new Map())
              setPage(0)
            }}
            options={scope.stores.map(s => ({ value: s.id, label: s.name }))}
          />
          <Input
            placeholder='Найти карточку'
            aria-label='Поиск для объединения'
            value={search}
            onChange={event => {
              setSearch(event.target.value)
              setPage(0)
            }}
          />
          <ErrorNotice error={query.error ?? save.error} />
          {query.isPending ? (
            <Loading />
          ) : (
            <div className='grouping-products'>
              {query.data?.items
                .flatMap(m => m.products)
                .map(p => (
                  <label key={p.id || p.nm_id || p.external_id}>
                    <input
                      type='checkbox'
                      checked={chosen.has(article(p) || '')}
                      disabled={save.isPending}
                      onChange={() => toggle(p)}
                    />
                    <span>
                      {p.title}
                      <small>{p.vendor_code}</small>
                    </span>
                  </label>
                ))}
            </div>
          )}
          <TablePagination
            page={page}
            pageSize={25}
            total={query.data?.total ?? 0}
            onPage={setPage}
            busy={query.isFetching}
            label='карточек для объединения'
          />
          <span>Выбрано: {chosen.size}</span>
          <Input
            aria-label='Название объединения'
            placeholder='Название объединения'
            maxLength={200}
            value={title}
            onChange={event => setTitle(event.target.value)}
          />
          <ChoiceSelect
            label='Действие с карточками'
            value={action}
            onChange={value => setAction(value as typeof action)}
            options={[
              { value: 'merge', label: 'Объединить выбранные' },
              { value: 'split', label: 'Разъединить выбранные' },
              { value: 'reset', label: 'Вернуть объединение площадки' }
            ]}
          />
          <Button
            disabled={
              save.isPending ||
              chosen.size === 0 ||
              chosen.size > 200 ||
              (action === 'merge' && chosen.size < 2)
            }
            onClick={() => save.mutate()}
          >
            {save.isPending ? 'Сохраняем…' : 'Применить'}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
