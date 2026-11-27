'use client'

import { useQuery } from '@tanstack/react-query'
import { useRef, useState } from 'react'

import {
  type CatalogImportResult,
  catalogMatchDelete,
  catalogMatchesApply,
  catalogMatchesAutomatic,
  catalogMatchesCorrections,
  catalogMatchesList,
  catalogMatchesPreview,
  catalogMatchesTemplate,
  catalogMatchesUnmatched,
  inventoryPackagingApply,
  inventoryPackagingPreview,
  inventoryPackagingTemplate
} from '@app/api'

import { ChoiceSelect } from '@/components/choice-select'
import { Empty, ErrorNotice } from '@/components/feedback'
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

import { downloadFile, downloadResponse } from '@/lib/download'

export function CatalogImportDialog({
  kind,
  onClose,
  onSaved
}: {
  kind: 'packaging' | 'matching'
  onClose: () => void
  onSaved: () => void
}) {
  const scope = useWorkspace(),
    { user } = useAuth()
  const matching = kind === 'matching'
  const stores = scope.stores.filter(
    store => !matching || store.marketplace === 'wildberries'
  )
  const [left, setLeft] = useState(
    scope.store && stores.some(s => s.id === scope.store!.id)
      ? scope.store.id
      : (stores[0]?.id ?? '')
  )
  const ozon = scope.stores.filter(s => s.marketplace === 'ozon')
  const [right, setRight] = useState(ozon[0]?.id ?? '')
  const [page, setPage] = useState(0)
  const [result, setResult] = useState<CatalogImportResult | null>(null)
  const [fileError, setFileError] = useState<Error | null>(null)
  const [manual, setManual] = useState(false)
  const [removeId, setRemoveId] = useState('')
  const file = useRef<File | null>(null)
  const wid = scope.workspace!.id
  const pair = { left_store_id: left, right_store_id: right }
  const pairs = useQuery({
    queryKey: [
      'user',
      user?.id,
      wid,
      scope.accessKey,
      'catalog-matches',
      left,
      right,
      page
    ],
    queryFn: ({ signal }) =>
      catalogMatchesList(
        wid,
        { ...pair, limit: 25, offset: page * 25 },
        { signal }
      ),
    enabled: matching && !!left && !!right
  })
  const download = useProtectedAction(
    signal =>
      matching
        ? catalogMatchesTemplate(wid, { signal, responseType: 'blob' })
        : inventoryPackagingTemplate(wid, left, {
            signal,
            responseType: 'blob'
          }),
    blob =>
      downloadFile(
        blob,
        matching ? 'perk-wb-ozon-matches.xlsx' : 'perk-box-multiples.xlsx'
      ),
    { refresh: false }
  )
  const preview = useProtectedAction(
    signal => {
      if (!file.current) throw new Error('Выберите файл Excel')
      return matching
        ? catalogMatchesPreview(wid, { file: file.current }, pair, { signal })
        : inventoryPackagingPreview(
            wid,
            left,
            { file: file.current },
            { signal }
          )
    },
    setResult,
    { refresh: false }
  )
  const automatic = useProtectedAction(
    signal => catalogMatchesAutomatic(wid, pair, { signal }),
    setResult,
    { refresh: false }
  )
  const downloadCorrections = useProtectedAction(
    signal =>
      downloadResponse(
        file.current && result?.errors?.length
          ? catalogMatchesCorrections(wid, { file: file.current }, pair, {
              signal,
              responseType: 'blob'
            })
          : catalogMatchesUnmatched(
              wid,
              { ...pair, preview_id: result?.preview_id ?? undefined },
              { signal, responseType: 'blob' }
            )
      ),
    blob =>
      downloadFile(
        blob,
        `perk-matches-corrections.${blob.type.includes('application/zip') ? 'zip' : 'xlsx'}`
      ),
    { refresh: false }
  )
  const apply = useProtectedAction(
    signal => {
      if (!result?.preview_id) throw new Error('Сначала проверьте файл')
      return matching
        ? catalogMatchesApply(wid, result.preview_id, pair, { signal })
        : inventoryPackagingApply(wid, left, result.preview_id, { signal })
    },
    () => {
      onSaved()
      onClose()
    }
  )
  const remove = useProtectedAction(
    signal => catalogMatchDelete(wid, removeId, { signal }),
    async () => {
      setRemoveId('')
      await pairs.refetch()
    }
  )
  const busy =
    preview.isPending ||
    automatic.isPending ||
    apply.isPending ||
    download.isPending ||
    remove.isPending ||
    downloadCorrections.isPending
  const valid = !!left && (!matching || !!right)
  const change = () => {
    setResult(null)
    setPage(0)
    file.current = null
    setManual(false)
    setFileError(null)
  }
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
          <DialogTitle>
            {matching ? 'Соответствия WB и Ozon' : 'Вложимость коробов'}
          </DialogTitle>
        </DialogHeader>
        <div className='form-stack'>
          <div className='date-fields'>
            <ChoiceSelect
              label={matching ? 'Кабинет WB' : 'Кабинет для коробов'}
              value={left}
              disabled={busy || !!result?.can_apply}
              onChange={value => {
                setLeft(value)
                change()
              }}
              options={stores.map(s => ({ value: s.id, label: s.name }))}
            />
            {matching && (
              <ChoiceSelect
                label='Кабинет Ozon'
                value={right}
                disabled={busy || !!result?.can_apply}
                onChange={value => {
                  setRight(value)
                  change()
                }}
                options={ozon.map(s => ({ value: s.id, label: s.name }))}
              />
            )}
          </div>
          {!valid ? (
            <Empty
              title={
                matching ? 'Подключите кабинеты WB и Ozon' : 'Выберите кабинет'
              }
            />
          ) : (
            <>
              <div className='catalog-heading-actions'>
                <Button
                  variant='outline'
                  disabled={busy}
                  onClick={() => download.mutate()}
                >
                  Скачать шаблон
                </Button>
                {matching && (
                  <Button
                    variant='outline'
                    disabled={busy}
                    onClick={() => {
                      setResult(null)
                      file.current = null
                      setManual(false)
                      automatic.mutate()
                    }}
                  >
                    Подобрать по штрихкодам
                  </Button>
                )}
                {matching && (
                  <Button
                    variant='outline'
                    disabled={busy}
                    onClick={() => downloadCorrections.mutate()}
                  >
                    {manual && result?.errors?.length
                      ? 'Скачать файл для исправления'
                      : 'Несопоставленные товары'}
                  </Button>
                )}
              </div>
              <label className='form-stack'>
                Файл Excel
                <Input
                  type='file'
                  accept='.xlsx'
                  disabled={busy}
                  onChange={event => {
                    const selected = event.target.files?.[0] ?? null
                    file.current = null
                    setResult(null)
                    setFileError(null)
                    if (
                      selected &&
                      (!selected.name.toLowerCase().endsWith('.xlsx') ||
                        selected.size > 256 * 1024)
                    ) {
                      setFileError(new Error('Выберите XLSX до 256 КБ'))
                      return
                    }
                    file.current = selected
                    setManual(!!selected)
                    if (selected) preview.mutate()
                  }}
                />
              </label>
              <ErrorNotice
                error={
                  fileError ??
                  preview.error ??
                  automatic.error ??
                  apply.error ??
                  download.error ??
                  downloadCorrections.error ??
                  remove.error ??
                  pairs.error
                }
              />
              {result && (
                <section className='catalog-import-preview'>
                  <strong>Готово к сохранению: {result.valid_count}</strong>
                  {!!result.errors?.length && (
                    <ul role='alert'>
                      {result.errors?.map((error, i) => (
                        <li key={i}>
                          {error.row ? `Строка ${error.row}: ` : ''}
                          {error.message}
                        </li>
                      ))}
                    </ul>
                  )}
                  {!!result.items?.length && (
                    <div className='table-scroll'>
                      <table className='data-table'>
                        <thead>
                          <tr>
                            <th>Артикул {matching ? 'WB' : ''}</th>
                            <th>{matching ? 'Артикул Ozon' : 'В коробе'}</th>
                          </tr>
                        </thead>
                        <tbody>
                          {result.items?.map((row, i) => (
                            <tr key={i}>
                              <td>
                                {row.vendor_code}
                                <small>{row.barcode}</small>
                              </td>
                              <td>
                                {matching ? (
                                  <>
                                    {row.right_vendor_code}
                                    <small>{row.right_barcode}</small>
                                  </>
                                ) : (
                                  row.box_multiple
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                  <div className='catalog-heading-actions'>
                    <Button
                      disabled={busy || !result.can_apply}
                      onClick={() => apply.mutate()}
                    >
                      {apply.isPending ? 'Сохраняем…' : 'Сохранить'}
                    </Button>
                    <Button
                      variant='ghost'
                      disabled={busy}
                      onClick={() => setResult(null)}
                    >
                      Другой файл
                    </Button>
                  </div>
                </section>
              )}
              {matching && !result && !!pairs.data?.items.length && (
                <section>
                  <h3>Сохранённые соответствия</h3>
                  <div className='table-scroll'>
                    <table className='data-table'>
                      <thead>
                        <tr>
                          <th>WB</th>
                          <th>Ozon</th>
                          <th />
                        </tr>
                      </thead>
                      <tbody>
                        {pairs.data.items.map(row => (
                          <tr key={row.id}>
                            <td>
                              {row.left_vendor_code}
                              <small>{row.left_barcode}</small>
                            </td>
                            <td>
                              {row.right_vendor_code}
                              <small>{row.right_barcode}</small>
                            </td>
                            <td>
                              {removeId === row.id ? (
                                <>
                                  <Button
                                    variant='destructive'
                                    disabled={busy}
                                    onClick={() => remove.mutate()}
                                  >
                                    Удалить
                                  </Button>
                                  <Button
                                    variant='ghost'
                                    onClick={() => setRemoveId('')}
                                  >
                                    Отмена
                                  </Button>
                                </>
                              ) : (
                                <Button
                                  variant='ghost'
                                  onClick={() => setRemoveId(row.id)}
                                >
                                  Удалить
                                </Button>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <TablePagination
                    page={page}
                    pageSize={25}
                    total={pairs.data.count}
                    onPage={setPage}
                    busy={pairs.isFetching}
                    label='соответствий'
                  />
                </section>
              )}
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
