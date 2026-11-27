import { zodResolver } from '@hookform/resolvers/zod'
import { useForm } from 'react-hook-form'

import { type SupplyParameters, supplyPlanCreateSchema } from '@app/schemas'

import { type PlanView, supplyPlanCreate } from '@app/api'

import { ErrorNotice } from '@/components/feedback'
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

import { platformName } from '@/features/products/model/catalog'
import { useWorkspace } from '@/features/workspace/workspace-provider'

import { useProtectedAction } from '@/hooks/use-protected-action'

export function CreatePlanDialog({
  parameters,
  storeId,
  destination,
  urgent,
  onClose,
  onCreated
}: {
  parameters: SupplyParameters
  storeId?: string
  destination?: { id: string; name: string }
  urgent: boolean
  onClose: () => void
  onCreated: (plan: PlanView) => void
}) {
  const scope = useWorkspace()
  const stores = scope.selected.filter(store =>
    store.features.includes('supplies')
  )
  const form = useForm({
    resolver: zodResolver(supplyPlanCreateSchema),
    defaultValues: {
      ...parameters,
      urgent_only: urgent,
      title: 'План поставки',
      destination: destination?.name ?? '',
      store_id: storeId || (stores.length === 1 ? stores[0].id : '')
    }
  })
  const create = useProtectedAction(signal => {
    const { store_id, ...data } = supplyPlanCreateSchema.parse(form.getValues())
    return supplyPlanCreate(
      scope.workspace!.id,
      store_id,
      { ...data, destination_id: destination?.id },
      { signal }
    )
  }, onCreated)
  return (
    <Dialog
      open
      onOpenChange={open => {
        if (!open) onClose()
      }}
    >
      <DialogContent className='sm:max-w-md'>
        <DialogHeader>
          <DialogTitle>Новый план поставки</DialogTitle>
          <DialogDescription>
            Добавьте товары после создания плана.
          </DialogDescription>
        </DialogHeader>
        <form
          className='form-stack'
          onSubmit={form.handleSubmit(() => create.mutate())}
        >
          <fieldset
            className='form-stack'
            disabled={create.isPending}
          >
            <FormField
              label='Кабинет для плана'
              error={form.formState.errors.store_id?.message}
            >
              <select
                className='native-select'
                disabled={!!destination}
                {...form.register('store_id')}
              >
                <option value=''>Выберите кабинет</option>
                {stores.map(store => (
                  <option
                    key={store.id}
                    value={store.id}
                  >
                    {store.name} · {platformName(store.marketplace)}
                  </option>
                ))}
              </select>
            </FormField>
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
                readOnly={!!destination}
                {...form.register('destination')}
              />
            </FormField>
            <ErrorNotice error={create.error} />
            <Button type='submit'>
              {create.isPending ? 'Создаём…' : 'Создать план'}
            </Button>
          </fieldset>
        </form>
      </DialogContent>
    </Dialog>
  )
}
