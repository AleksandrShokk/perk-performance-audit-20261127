import { zodResolver } from '@hookform/resolvers/zod'
import { useForm } from 'react-hook-form'

import { supplyPackagingSchema } from '@app/schemas'

import { type ReplenishmentItem, inventoryPackagingSave } from '@app/api'

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

import { useWorkspace } from '@/features/workspace/workspace-provider'

import { useProtectedAction } from '@/hooks/use-protected-action'

export function PackagingDialog({
  item,
  onClose
}: {
  item: ReplenishmentItem
  onClose: () => void
}) {
  const scope = useWorkspace()
  const form = useForm({
    resolver: zodResolver(supplyPackagingSchema),
    defaultValues: { box_multiple: item.box_multiple ?? 1 }
  })
  const save = useProtectedAction(
    signal =>
      inventoryPackagingSave(
        scope.workspace!.id,
        item.store_id,
        item.id || item.nm_id,
        supplyPackagingSchema.parse(form.getValues()),
        { signal }
      ),
    onClose
  )
  return (
    <Dialog
      open
      onOpenChange={open => {
        if (!open) onClose()
      }}
    >
      <DialogContent className='max-w-md'>
        <DialogHeader>
          <DialogTitle>Кратность коробов</DialogTitle>
          <DialogDescription>
            {item.title} · {item.store_name}
          </DialogDescription>
        </DialogHeader>
        <form
          className='form-stack'
          onSubmit={form.handleSubmit(() => save.mutate())}
        >
          <fieldset
            className='form-stack'
            disabled={save.isPending}
          >
            <FormField
              label='Товаров в коробе'
              error={form.formState.errors.box_multiple?.message}
            >
              <Input
                type='number'
                inputMode='numeric'
                min={1}
                max={10000}
                step={1}
                {...form.register('box_multiple', { valueAsNumber: true })}
              />
            </FormField>
            <ErrorNotice error={save.error} />
            <Button type='submit'>
              {save.isPending ? 'Сохраняем…' : 'Сохранить кратность'}
            </Button>
          </fieldset>
        </form>
      </DialogContent>
    </Dialog>
  )
}
