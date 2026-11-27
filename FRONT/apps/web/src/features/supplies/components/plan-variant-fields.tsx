import { useWatch } from 'react-hook-form'

import type { PlanLine } from '@app/api'

import { FormField } from '@/components/form-field'
import { Input } from '@/components/ui/input'

import type { PlanFormApi } from '../model/plans'

export function PlanVariantFields({
  item,
  index,
  form,
  disabled
}: {
  item: PlanLine
  index: number
  form: PlanFormApi
  disabled: boolean
}) {
  const values =
    useWatch({ control: form.control, name: `items.${index}.variants` }) ?? []
  const total = useWatch({
    control: form.control,
    name: `items.${index}.quantity`
  })
  const allocated = values.reduce(
    (sum, row) => sum + (Number.isFinite(row.quantity) ? row.quantity : 0),
    0
  )
  const article = item.vendor_code || item.marketplace_code || item.nm_id
  return (
    <fieldset
      className='supply-variant-fields'
      disabled={disabled}
    >
      <div
        className={
          allocated > total ? 'text-destructive' : 'text-muted-foreground'
        }
      >
        Распределено {allocated} из {Number.isFinite(total) ? total : 0} шт.
      </div>
      {(item.variants ?? []).map((variant, position) => {
        const size =
          variant.size && variant.size !== '0' ? variant.size : 'Без размера'
        const errors =
          form.formState.errors.items?.[index]?.variants?.[position]
        return (
          <div
            className='supply-variant-row'
            key={variant.variant_id}
          >
            <span>{size}</span>
            <FormField
              label='Штрихкод'
              error={errors?.barcode?.message}
            >
              <select
                aria-label={'Штрихкод ' + article + ' · ' + size}
                className='native-select'
                {...form.register(
                  `items.${index}.variants.${position}.barcode`
                )}
              >
                <option value=''>
                  {variant.barcodes.length
                    ? 'Выберите штрихкод'
                    : 'Нет штрихкодов в каталоге'}
                </option>
                {variant.barcodes.map(code => (
                  <option
                    key={code}
                    value={code}
                  >
                    {code}
                  </option>
                ))}
              </select>
            </FormField>
            <FormField
              label='Количество'
              error={errors?.quantity?.message}
            >
              <Input
                aria-label={'Количество ' + article + ' · ' + size}
                type='number'
                inputMode='numeric'
                min={0}
                max={2147483647}
                step={1}
                {...form.register(
                  `items.${index}.variants.${position}.quantity`,
                  {
                    valueAsNumber: true,
                    onChange: event => {
                      if (item.variants?.length === 1)
                        form.setValue(
                          `items.${index}.quantity`,
                          event.target.valueAsNumber,
                          { shouldDirty: true }
                        )
                    }
                  }
                )}
              />
            </FormField>
          </div>
        )
      })}
    </fieldset>
  )
}
