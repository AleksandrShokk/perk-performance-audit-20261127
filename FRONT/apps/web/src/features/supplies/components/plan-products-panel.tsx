import { useQuery } from '@tanstack/react-query'
import { useRef, useState } from 'react'

import {
  type PlanView,
  supplyPlanImport,
  supplyPlanProducts,
  supplyPlanProductsAdd,
  supplyTemplateBlank
} from '@app/api'

import { Empty, ErrorNotice, Loading } from '@/components/feedback'
import { FileDropzone } from '@/components/file-dropzone'
import { ProductLabel } from '@/components/product-label'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

import { useAuth } from '@/features/auth/auth-provider'
import { useWorkspace } from '@/features/workspace/workspace-provider'

import { useDebouncedValue } from '@/hooks/use-debounced-value'
import { useProtectedAction } from '@/hooks/use-protected-action'

import { downloadFile } from '@/lib/download'

import { supplyPageSize } from '../hooks/use-supplies'
import { validateTemplateFile } from '../model/template'

import { SupplyPagination } from './supply-pagination'

export function PlanProductsPanel({
  plan,
  onBack,
  onChanged
}: {
  plan: PlanView
  onBack: () => void
  onChanged: () => Promise<unknown>
}) {
  const scope = useWorkspace(),
    { user } = useAuth()
  const [search, setSearch] = useState(''),
    [page, setPage] = useState(0)
  const [selected, setSelected] = useState<string[]>([])
  const queryText = useDebouncedValue(search)
  const file = useRef<File | null>(null)
  const [fileError, setFileError] = useState<Error | null>(null)
  const query = useQuery({
    queryKey: [
      'user',
      user?.id,
      scope.workspace?.id,
      scope.accessKey,
      'plan-products',
      plan.id,
      plan.revision,
      queryText,
      page
    ],
    queryFn: ({ signal }) =>
      supplyPlanProducts(
        scope.workspace!.id,
        plan.id,
        {
          query: queryText,
          limit: supplyPageSize,
          offset: page * supplyPageSize
        },
        { signal }
      ),
    gcTime: 0
  })
  const changed = async () => {
    await onChanged()
    onBack()
  }
  const add = useProtectedAction(
    signal =>
      supplyPlanProductsAdd(
        scope.workspace!.id,
        plan.id,
        { revision: plan.revision, product_keys: selected },
        { signal }
      ),
    changed
  )
  const upload = useProtectedAction(signal => {
    if (!file.current) throw new Error('Выберите файл')
    return supplyPlanImport(
      scope.workspace!.id,
      plan.id,
      { file: file.current },
      { revision: plan.revision },
      { signal }
    )
  }, changed)
  const blank = useProtectedAction(
    signal => supplyTemplateBlank(scope.workspace!.id, plan.id, { signal }),
    blob => downloadFile(blob, `perk-${plan.marketplace}-blank.xlsx`),
    { refresh: false }
  )
  const busy = add.isPending || upload.isPending || blank.isPending
  return (
    <section
      className='supply-template-panel'
      aria-label='Добавление товаров в план'
    >
      <div className='supply-template-content'>
        <FileDropzone
          label='Загрузить товары из XLSX'
          disabled={busy}
          onFile={selectedFile => {
            setFileError(null)
            upload.reset()
            try {
              validateTemplateFile(selectedFile)
              file.current = selectedFile
              upload.mutate()
            } catch (error) {
              setFileError(error as Error)
            }
          }}
        />
        <Button
          type='button'
          variant='outline'
          disabled={busy}
          onClick={() => blank.mutate()}
        >
          Скачать шаблон для заполнения
        </Button>
        {upload.isPending && <p role='status'>Проверяем товары…</p>}
        <ErrorNotice
          error={fileError ?? upload.error ?? blank.error ?? add.error}
        />
        <Input
          aria-label='Поиск товаров для плана'
          placeholder='Название, артикул или штрихкод'
          value={search}
          onChange={event => {
            setSearch(event.target.value)
            setPage(0)
          }}
        />
        <ErrorNotice
          error={query.error}
          onRetry={() => void query.refetch()}
        />
        {query.isPending ? (
          <Loading />
        ) : (
          <div className='supply-plan-candidates'>
            {query.data?.items.map(item => (
              <label
                className='supply-plan-candidate'
                key={item.product_key}
              >
                <input
                  type='checkbox'
                  disabled={busy}
                  checked={selected.includes(item.product_key)}
                  onChange={event =>
                    setSelected(keys =>
                      event.target.checked
                        ? [...keys, item.product_key]
                        : keys.filter(key => key !== item.product_key)
                    )
                  }
                />
                <ProductLabel
                  title={item.title}
                  article={
                    item.vendor_code || item.marketplace_code || item.nm_id
                  }
                  photo={item.photo}
                />
              </label>
            ))}
            {!query.data?.count && <Empty title='Товары не найдены' />}
          </div>
        )}
        <SupplyPagination
          page={page}
          count={query.data?.count ?? 0}
          busy={busy || query.isFetching}
          onPage={setPage}
        />
      </div>
      <footer className='supply-plan-footer'>
        <Button
          type='button'
          variant='outline'
          disabled={busy}
          onClick={onBack}
        >
          К плану
        </Button>
        <Button
          type='button'
          disabled={busy || !selected.length}
          onClick={() => add.mutate()}
        >
          Добавить выбранные · {selected.length}
        </Button>
      </footer>
    </section>
  )
}
