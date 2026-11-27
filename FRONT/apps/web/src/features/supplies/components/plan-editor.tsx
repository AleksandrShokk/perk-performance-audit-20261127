import { formatUnits } from '@app/analytics/format'
import { zodResolver } from '@hookform/resolvers/zod'
import { Download } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useForm, useWatch } from 'react-hook-form'

import {
  type SupplyPlanFormValues,
  type SupplyPlanValues,
  supplyPlanUpdateSchema
} from '@app/schemas'

import {
  type PlanView,
  supplyPlanDelete,
  supplyPlanExport,
  supplyPlanItemsExport,
  supplyPlanSave,
  supplyPlanVariantsLoad
} from '@app/api'

import { Empty, ErrorNotice, Loading } from '@/components/feedback'
import { FormField } from '@/components/form-field'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'

import { useWorkspace } from '@/features/workspace/workspace-provider'

import { useProtectedAction } from '@/hooks/use-protected-action'

import { downloadFile } from '@/lib/download'

import { usePlan } from '../hooks/use-plans'
import { supplyPageSize } from '../hooks/use-supplies'
import { matchingPlanItems, planStatuses, planValues } from '../model/plans'

import { PlanProductRow } from './plan-product-row'
import { PlanProductsPanel } from './plan-products-panel'
import { SupplyPagination } from './supply-pagination'
import { TemplatePanel } from './template-panel'

export function PlanEditor({
  id,
  onClose
}: {
  id: string
  onClose: () => void
}) {
  const query = usePlan(id)
  const [template, setTemplate] = useState(false)
  return (
    <Dialog
      open
      onOpenChange={open => {
        if (!open) onClose()
      }}
    >
      <DialogContent className='supply-plan-dialog sm:max-w-5xl'>
        <DialogHeader>
          <DialogTitle>
            {template ? 'Шаблон поставки' : 'План поставки'}
          </DialogTitle>
          <DialogDescription>
            {query.data?.store_name || 'Сохранённый план'}
          </DialogDescription>
        </DialogHeader>
        <ErrorNotice
          error={query.error}
          onRetry={() => void query.refetch()}
        />
        {query.isPending ? (
          <Loading />
        ) : query.data ? (
          template ? (
            <TemplatePanel
              plan={query.data}
              onBack={() => {
                setTemplate(false)
                void query.refetch()
              }}
            />
          ) : (
            <PlanForm
              onTemplate={() => setTemplate(true)}
              key={query.data.id + ':' + query.data.revision}
              plan={query.data}
              onClose={onClose}
              onReload={() => query.refetch()}
            />
          )
        ) : null}
      </DialogContent>
    </Dialog>
  )
}

function PlanForm({
  plan,
  onClose,
  onReload,
  onTemplate
}: {
  plan: PlanView
  onClose: () => void
  onReload: () => Promise<unknown>
  onTemplate: () => void
}) {
  const scope = useWorkspace()
  const [search, setSearch] = useState(''),
    [page, setPage] = useState(0)
  const [adding, setAdding] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const schema = useMemo(() => supplyPlanUpdateSchema(plan.items), [plan.items])
  const form = useForm<SupplyPlanFormValues, unknown, SupplyPlanValues>({
    resolver: zodResolver(schema),
    defaultValues: planValues(plan)
  })
  const quantities = useWatch({ control: form.control, name: 'items' })
  const total = quantities.reduce(
    (sum, row) => sum + (Number.isFinite(row.quantity) ? row.quantity : 0),
    0
  )
  const rows = useMemo(
    () =>
      matchingPlanItems(
        {
          ...plan,
          items: quantities.map(value =>
            plan.items.find(item => item.product_key === value.product_key)!
          )
        },
        search
      ),
    [plan, search, quantities]
  )
  const removePlan = useProtectedAction(
    signal =>
      supplyPlanDelete(
        scope.workspace!.id,
        plan.id,
        { revision: plan.revision },
        { signal }
      ),
    onClose
  )
  const save = useProtectedAction(
    signal =>
      supplyPlanSave(
        scope.workspace!.id,
        plan.id,
        schema.parse(form.getValues()),
        { signal }
      ),
    onClose
  )
  const download = useProtectedAction(
    signal =>
      supplyPlanExport(scope.workspace!.id, plan.id, {
        signal,
        responseType: 'blob'
      }),
    file => downloadFile(file, 'perk-supply-plan.csv'),
    { refresh: false }
  )
  const itemsDownload = useProtectedAction(
    signal =>
      supplyPlanItemsExport(scope.workspace!.id, plan.id, {
        signal,
        responseType: 'blob'
      }),
    file => downloadFile(file, 'perk-supply-variants.csv'),
    { refresh: false }
  )
  const load = useProtectedAction(
    signal =>
      supplyPlanVariantsLoad(
        scope.workspace!.id,
        plan.id,
        { revision: plan.revision },
        { signal }
      ),
    async () => {
      await onReload()
    }
  )
  const missingVariants = plan.items.some(
    item => item.quantity > 0 && !item.variants?.length
  )
  const busy =
    save.isPending ||
    download.isPending ||
    itemsDownload.isPending ||
    load.isPending ||
    removePlan.isPending
  if (adding)
    return (
      <PlanProductsPanel
        plan={plan}
        onBack={() => setAdding(false)}
        onChanged={onReload}
      />
    )
  return (
    <form
      className='supply-plan-form'
      noValidate
      onSubmit={form.handleSubmit(
        () => save.mutate(),
        errors => {
          const index = errors.items?.findIndex?.(error => !!error)
          if (index != null && index >= 0) {
            setSearch('')
            setPage(Math.floor(index / supplyPageSize))
          }
        }
      )}
    >
      <fieldset
        className='supply-plan-fields'
        disabled={busy || !scope.admin}
      >
        <FormField
          label='Название плана'
          error={form.formState.errors.title?.message}
        >
          <Input
            maxLength={120}
            {...form.register('title')}
          />
        </FormField>
        <FormField
          label='Склад / кластер'
          error={form.formState.errors.destination?.message}
        >
          <Input
            maxLength={160}
            placeholder='Необязательно'
            readOnly={!!plan.destination_id}
            {...form.register('destination')}
          />
        </FormField>
        <FormField
          label='Статус плана'
          error={form.formState.errors.status?.message}
        >
          <select
            className='native-select'
            {...form.register('status')}
          >
            {Object.entries(planStatuses).map(([value, title]) => (
              <option
                key={value}
                value={value}
              >
                {title}
              </option>
            ))}
          </select>
        </FormField>
      </fieldset>
      {scope.admin && (
        <div className='supply-plan-actions'>
          <Button
            type='button'
            variant='outline'
            disabled={busy || form.formState.isDirty}
            onClick={() => setAdding(true)}
          >
            Добавить товары
          </Button>
          {form.formState.isDirty && (
            <span className='text-muted-foreground'>
              Сохраните изменения перед добавлением товаров
            </span>
          )}
        </div>
      )}
      <div className='supply-plan-search'>
        <Input
          aria-label='Поиск в плане'
          placeholder='Название, артикул или штрихкод'
          value={search}
          onChange={event => {
            setSearch(event.target.value)
            setPage(0)
          }}
        />
        <strong>{formatUnits(total)}</strong>
      </div>
      <div className='supply-plan-items'>
        <table className='supply-data'>
          <thead>
            <tr>
              <th>Товар</th>
              <th>В коробе</th>
              <th>Рекомендовано</th>
              <th>К поставке</th>
            </tr>
          </thead>
          <tbody>
            {rows
              .slice(page * supplyPageSize, (page + 1) * supplyPageSize)
              .map(({ item, index }) => (
                <PlanProductRow
                  key={item.product_key}
                  item={item}
                  index={index}
                  form={form}
                  onRemove={() => {
                    form.setValue(
                      'items',
                      quantities.filter(
                        value => value.product_key !== item.product_key
                      ),
                      { shouldDirty: true }
                    )
                    setPage(0)
                  }}
                  disabled={busy || !scope.admin}
                />
              ))}
          </tbody>
        </table>
        {!rows.length && (
          <Empty
            title={
              plan.items.length
                ? 'Товары не найдены'
                : 'План пуст. Добавьте нужные товары'
            }
          />
        )}
      </div>
      <SupplyPagination
        page={page}
        count={rows.length}
        busy={busy}
        onPage={setPage}
      />
      <ErrorNotice
        error={
          save.error ??
          download.error ??
          itemsDownload.error ??
          load.error ??
          removePlan.error
        }
      />
      <footer className='supply-plan-footer'>
        {scope.admin &&
          (confirmDelete ? (
            <>
              <span>Удалить план?</span>
              <Button
                type='button'
                variant='outline'
                disabled={busy}
                onClick={() => setConfirmDelete(false)}
              >
                Отмена
              </Button>
              <Button
                type='button'
                variant='destructive'
                disabled={busy}
                onClick={() => removePlan.mutate()}
              >
                Удалить навсегда
              </Button>
            </>
          ) : (
            <Button
              type='button'
              variant='ghost'
              disabled={busy}
              onClick={() => setConfirmDelete(true)}
            >
              Удалить план
            </Button>
          ))}

        {scope.can('reports.export') && (
          <Button
            type='button'
            variant='outline'
            disabled={busy || form.formState.isDirty || !plan.quantity}
            onClick={onTemplate}
          >
            Заполнить XLSX
          </Button>
        )}
        {scope.admin && missingVariants && (
          <Button
            type='button'
            variant='outline'
            disabled={busy || form.formState.isDirty}
            onClick={() => load.mutate()}
          >
            {load.isPending ? 'Загружаем…' : 'Загрузить размеры'}
          </Button>
        )}
        {scope.can('reports.export') && (
          <Button
            type='button'
            variant='outline'
            disabled={
              busy || form.formState.isDirty || !plan.allocation_complete
            }
            title={
              form.formState.isDirty
                ? 'Сначала сохраните изменения'
                : (plan.allocation_error ?? undefined)
            }
            onClick={() => itemsDownload.mutate()}
          >
            <Download size={15} />
            {itemsDownload.isPending ? 'Готовим размеры…' : 'Выгрузить размеры'}
          </Button>
        )}
        {scope.can('reports.export') && (
          <Button
            type='button'
            variant='outline'
            disabled={busy || form.formState.isDirty || !plan.quantity}
            title={
              form.formState.isDirty ? 'Сначала сохраните изменения' : undefined
            }
            onClick={() => download.mutate()}
          >
            <Download size={15} />
            {download.isPending ? 'Готовим файл…' : 'Скачать CSV'}
          </Button>
        )}
        {scope.admin && (
          <Button
            type='submit'
            disabled={busy || !form.formState.isDirty}
          >
            {save.isPending ? 'Сохраняем…' : 'Сохранить план'}
          </Button>
        )}
      </footer>
    </form>
  )
}
