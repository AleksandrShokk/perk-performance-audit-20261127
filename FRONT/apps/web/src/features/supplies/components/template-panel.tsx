import { formatNumber, formatUnits } from '@app/analytics/format'
import { zodResolver } from '@hookform/resolvers/zod'
import { ArrowLeft, Download } from 'lucide-react'
import { useRef, useState } from 'react'
import { useForm, useWatch } from 'react-hook-form'

import {
  type SupplyTemplateMapping,
  type SupplyTemplateMappingInput,
  supplyTemplateMappingSchema
} from '@app/schemas'

import {
  type PlanView,
  type TemplateInspection,
  supplyTemplateBlank,
  supplyTemplateFill,
  supplyTemplateInspect
} from '@app/api'

import { Empty, ErrorNotice } from '@/components/feedback'
import { FileDropzone } from '@/components/file-dropzone'
import { FormField } from '@/components/form-field'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

import { useWorkspace } from '@/features/workspace/workspace-provider'

import { useProtectedAction } from '@/hooks/use-protected-action'

import { downloadFile, downloadResponse } from '@/lib/download'

import {
  emptyTemplateMapping,
  initialTemplateMapping,
  validateTemplateFile
} from '../model/template'

export function TemplatePanel({
  plan,
  onBack
}: {
  plan: PlanView
  onBack: () => void
}) {
  const scope = useWorkspace()
  const file = useRef<File | null>(null)
  const [metadata, setMetadata] = useState<TemplateInspection | null>(null)
  const [fileError, setFileError] = useState<Error | null>(null)
  const form = useForm<
    SupplyTemplateMappingInput,
    unknown,
    SupplyTemplateMapping
  >({
    resolver: zodResolver(supplyTemplateMappingSchema),
    defaultValues: emptyTemplateMapping
  })
  const inspect = useProtectedAction(
    signal => {
      if (!file.current) throw new Error('Выберите исходный шаблон площадки')
      return supplyTemplateInspect(
        scope.workspace!.id,
        plan.id,
        { file: file.current },
        { signal }
      )
    },
    data => {
      setMetadata(data)
      form.reset(initialTemplateMapping(data))
    },
    { refresh: false }
  )
  const blank = useProtectedAction(
    signal => supplyTemplateBlank(scope.workspace!.id, plan.id, { signal }),
    blob => downloadFile(blob, `perk-${plan.marketplace}-blank.xlsx`),
    { refresh: false }
  )
  const fill = useProtectedAction(
    signal => {
      if (!file.current || !metadata)
        throw new Error('Сначала загрузите шаблон')
      const mapping = supplyTemplateMappingSchema.parse(form.getValues())
      const choice = metadata.choices.find(
        choice => choice.value === mapping.identifier_type
      )
      if (!choice || choice.error)
        throw new Error(choice?.error ?? 'Выберите идентификатор товара')
      return downloadResponse(
        supplyTemplateFill(
          scope.workspace!.id,
          plan.id,
          { file: file.current },
          {
            ...mapping,
            revision: metadata.revision,
            digest: metadata.digest,
            data_digest: choice.data_digest
          },
          { signal, responseType: 'blob' }
        )
      )
    },
    blob =>
      downloadFile(
        blob,
        `perk-supply-${plan.marketplace === 'ozon' ? 'ozon' : 'wb'}.xlsx`
      ),
    { refresh: false }
  )
  const [sheetName, headerRow, identifierType] = useWatch({
    control: form.control,
    name: ['sheet', 'header_row', 'identifier_type']
  })
  const busy = inspect.isPending || fill.isPending
  const sheet = metadata?.sheets.find(sheet => sheet.name === sheetName)
  const header = sheet?.headers.find(header => header.row === headerRow)
  const choice = metadata?.choices.find(
    choice => choice.value === identifierType
  )
  const changeHeader = (name: string, number?: number) => {
    const selected = metadata?.sheets.find(sheet => sheet.name === name)
    const row =
      selected?.headers.find(row => row.row === number) ?? selected?.headers[0]
    form.setValue('header_row', row?.row ?? 1)
    form.setValue('first_row', (row?.row ?? 1) + 1)
    form.setValue('identifier_column', row?.columns[0]?.key ?? 'A')
    form.setValue('quantity_column', row?.columns[1]?.key ?? 'B')
    form.clearErrors()
  }
  return (
    <form
      className='supply-template-panel'
      noValidate
      onSubmit={form.handleSubmit(() => fill.mutate())}
    >
      <div className='supply-template-content'>
        <Button
          type='button'
          variant='outline'
          disabled={blank.isPending}
          onClick={() => blank.mutate()}
        >
          Скачать пустой шаблон
        </Button>
        <ErrorNotice error={blank.error} />
        <p className='text-muted-foreground'>
          Заполните шаблон площадки товарами из плана.
        </p>
        <div className='field'>
          <span>Исходный шаблон XLSX</span>
          <FileDropzone
            label='Исходный шаблон XLSX'
            disabled={busy}
            onFile={selected => {
              setMetadata(null)
              inspect.reset()
              fill.reset()
              setFileError(null)
              file.current = null
              try {
                validateTemplateFile(selected)
                file.current = selected
                inspect.mutate()
              } catch (error) {
                setFileError(error as Error)
              }
            }}
          />
        </div>
        {inspect.isPending && <p role='status'>Проверяем шаблон…</p>}
        {metadata && (
          <>
            <fieldset
              className='supply-template-fields'
              disabled={busy}
            >
              <FormField
                label='Лист'
                error={form.formState.errors.sheet?.message}
              >
                <select
                  aria-label='Лист шаблона'
                  className='native-select'
                  {...form.register('sheet', {
                    onChange: event => changeHeader(event.target.value)
                  })}
                >
                  {metadata.sheets.map(sheet => (
                    <option
                      key={sheet.name}
                      value={sheet.name}
                    >
                      {sheet.name}
                    </option>
                  ))}
                </select>
              </FormField>
              <FormField
                label='Идентификатор товара'
                error={form.formState.errors.identifier_type?.message}
              >
                <select
                  aria-label='Идентификатор товара'
                  className='native-select'
                  {...form.register('identifier_type')}
                >
                  {metadata.choices.map(choice => (
                    <option
                      key={choice.value}
                      value={choice.value}
                      disabled={!!choice.error}
                    >
                      {choice.label}
                    </option>
                  ))}
                </select>
              </FormField>
              <FormField
                label='Столбец товара'
                error={form.formState.errors.identifier_column?.message}
              >
                <select
                  aria-label='Столбец товара'
                  className='native-select'
                  {...form.register('identifier_column')}
                >
                  {header?.columns.map(column => (
                    <option
                      key={column.key}
                      value={column.key}
                    >
                      {column.key} · {column.label}
                    </option>
                  ))}
                </select>
              </FormField>
              <FormField
                label='Столбец количества'
                error={form.formState.errors.quantity_column?.message}
              >
                <select
                  aria-label='Столбец количества'
                  className='native-select'
                  {...form.register('quantity_column')}
                >
                  {header?.columns.map(column => (
                    <option
                      key={column.key}
                      value={column.key}
                    >
                      {column.key} · {column.label}
                    </option>
                  ))}
                </select>
              </FormField>
              <FormField label='Заполнение'>
                <select
                  aria-label='Режим заполнения'
                  className='native-select'
                  {...form.register('mode')}
                >
                  <option value='append'>Пустой шаблон</option>
                  <option value='match'>Товары из плана, остальные — 0</option>
                </select>
              </FormField>
            </fieldset>
            <details className='supply-template-layout'>
              <summary>Разметка шаблона</summary>
              <fieldset
                className='supply-template-fields'
                disabled={busy}
              >
                <FormField
                  label='Строка заголовков'
                  error={form.formState.errors.header_row?.message}
                >
                  <select
                    aria-label='Строка заголовков'
                    className='native-select'
                    {...form.register('header_row', {
                      valueAsNumber: true,
                      onChange: event =>
                        changeHeader(
                          sheet?.name ?? '',
                          Number(event.target.value)
                        )
                    })}
                  >
                    {sheet?.headers.map(row => (
                      <option
                        key={row.row}
                        value={row.row}
                      >
                        {row.row} ·{' '}
                        {row.columns
                          .slice(0, 2)
                          .map(column => column.label)
                          .join(' / ')}
                      </option>
                    ))}
                  </select>
                </FormField>
                <FormField
                  label='Первая строка товаров'
                  error={form.formState.errors.first_row?.message}
                >
                  <Input
                    type='number'
                    min={2}
                    max={100}
                    step={1}
                    {...form.register('first_row', { valueAsNumber: true })}
                  />
                </FormField>
              </fieldset>
            </details>
            {choice && !choice.error && (
              <section
                className='supply-template-preview'
                aria-label='Предпросмотр заполнения'
              >
                <div>
                  {formatNumber(choice.count)} позиций ·{' '}
                  {formatUnits(choice.units)}
                </div>
                <table className='supply-data'>
                  <thead>
                    <tr>
                      <th>{choice.label}</th>
                      <th>Количество</th>
                    </tr>
                  </thead>
                  <tbody>
                    {choice.preview.map(row => (
                      <tr key={row.identifier}>
                        <td>{row.identifier}</td>
                        <td>{formatUnits(row.quantity)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>
            )}
            {!header && <Empty title='Выберите строку с заголовками' />}
          </>
        )}
        <ErrorNotice
          error={
            fileError ??
            inspect.error ??
            fill.error ??
            (choice?.error ? new Error(choice.error) : null)
          }
        />
      </div>
      <footer className='supply-plan-footer'>
        <Button
          type='button'
          variant='outline'
          onClick={onBack}
        >
          <ArrowLeft size={15} />К плану
        </Button>
        <Button
          type='submit'
          disabled={busy || !metadata || !header || !choice || !!choice.error}
        >
          <Download size={15} />
          {fill.isPending ? 'Заполняем…' : 'Скачать XLSX'}
        </Button>
      </footer>
    </form>
  )
}
