'use client'

import { currencySymbol, formatNumber } from '@app/analytics/format'
import { useMutation } from '@tanstack/react-query'
import { Download, FileSpreadsheet, Upload } from 'lucide-react'
import { useRef } from 'react'

import {
  costsApplyImport,
  costsDownloadTemplate,
  costsPreviewImport
} from '@app/api'

import { ErrorNotice } from '@/components/feedback'
import { displayDate } from '@/components/range-calendar'
import { Button } from '@/components/ui/button'

import { downloadFile } from '../model/download'

import type { StoreFormProps } from './expense-form'

export function CostImport({ workspaceId, storeId, onSaved }: StoreFormProps) {
  const input = useRef<HTMLInputElement>(null)
  const template = useMutation({
    mutationFn: async () => {
      const file = await costsDownloadTemplate(workspaceId, storeId)
      downloadFile(file, 'perk-costs.xlsx')
    }
  })
  const preview = useMutation({
    mutationFn: async (file: File) => {
      if (!file.name.toLowerCase().endsWith('.xlsx'))
        throw new Error('Выберите файл XLSX')
      if (file.size > 256 * 1024) throw new Error('Размер файла — до 256 КБ')
      return costsPreviewImport(workspaceId, storeId, { file })
    }
  })
  const apply = useMutation({
    mutationFn: () =>
      costsApplyImport(workspaceId, storeId, preview.data!.preview_id!),
    onSuccess: onSaved
  })
  const busy = preview.isPending || apply.isPending
  return (
    <div className='form-stack'>
      <ErrorNotice error={template.error ?? preview.error ?? apply.error} />
      <div className='cost-import-actions'>
        <Button
          variant='outline'
          onClick={() => template.mutate()}
          disabled={template.isPending}
        >
          <Download size={15} />
          {template.isPending ? 'Готовим шаблон…' : 'Скачать шаблон XLSX'}
        </Button>
        <Button
          variant='secondary'
          onClick={() => input.current?.click()}
          disabled={busy}
        >
          <Upload size={15} />
          {preview.isPending ? 'Проверяем файл…' : 'Загрузить файл'}
        </Button>
      </div>
      <input
        ref={input}
        className='sr-only'
        type='file'
        accept='.xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        aria-label='Файл себестоимости'
        onChange={event => {
          const file = event.target.files?.[0]
          if (file) {
            apply.reset()
            preview.reset()
            preview.mutate(file)
          }
          event.target.value = ''
        }}
      />
      {preview.data ? (
        <>
          <div className='cost-preview-status'>
            <FileSpreadsheet size={20} />
            <strong>
              Готово строк: {formatNumber(preview.data.valid_count)} из{' '}
              {formatNumber(preview.data.rows_count)}
            </strong>
          </div>
          {preview.data.errors.length > 0 && (
            <div
              className='import-errors'
              role='alert'
            >
              {preview.data.errors.slice(0, 8).map((error, index) => (
                <p key={`${error.row}:${index}`}>
                  Строка {error.row}: {error.message}
                </p>
              ))}
            </div>
          )}
          {preview.data.items.length > 0 && (
            <div className='table-scroll'>
              <table className='data-table cost-preview'>
                <thead>
                  <tr>
                    <th>Товар</th>
                    <th>Код</th>
                    <th>Себестоимость</th>
                    <th>Действует с</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.data.items.slice(0, 10).map(row => (
                    <tr key={row.row}>
                      <td>{row.product_title}</td>
                      <td>
                        {'nm_id' in row ? row.nm_id : row.marketplace_code}
                      </td>
                      <td>
                        {row.amount.replace('.', ',')}{' '}
                        {currencySymbol(row.currency)}
                      </td>
                      <td>{displayDate(row.effective_from)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <Button
            disabled={
              !preview.data.can_apply || !preview.data.preview_id || busy
            }
            onClick={() => apply.mutate()}
          >
            {apply.isPending ? 'Применяем…' : 'Применить себестоимость'}
          </Button>
        </>
      ) : (
        <div className='cost-import-empty'>
          <FileSpreadsheet
            size={34}
            strokeWidth={1.5}
          />
          <span>Заполните цены и даты в шаблоне</span>
        </div>
      )}
    </div>
  )
}
