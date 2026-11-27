import { formatNumber, formatUnits } from '@app/analytics/format'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { useState } from 'react'

import type { PlanLine } from '@app/api'

import { ProductLabel } from '@/components/product-label'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

import type { PlanFormApi } from '../model/plans'

import { PlanVariantFields } from './plan-variant-fields'

export function PlanProductRow({
  item,
  index,
  form,
  disabled,
  onRemove
}: {
  item: PlanLine
  index: number
  form: PlanFormApi
  disabled: boolean
  onRemove: () => void
}) {
  const [expanded, setExpanded] = useState(false)
  const article = item.vendor_code || item.marketplace_code || item.nm_id
  const hasVariants = !!item.variants?.length
  const open = expanded || !!form.formState.errors.items?.[index]?.variants
  return (
    <>
      <tr>
        <td>
          <ProductLabel
            title={item.title}
            article={article}
            photo={item.photo}
          />
          {hasVariants && (
            <Button
              type='button'
              className='supply-sizes-toggle'
              variant='ghost'
              size='sm'
              aria-label={'Размеры ' + article}
              aria-expanded={open}
              onClick={() => setExpanded(!expanded)}
            >
              {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
              Размеры · {item.variants!.length}
            </Button>
          )}
        </td>
        <td className='supply-numeric'>
          {formatNumber(item.box_multiple ?? 1)}
        </td>
        <td className='supply-numeric'>
          {formatUnits(item.recommended_quantity)}
        </td>
        <td className='supply-plan-quantity'>
          <Input
            aria-label={'К поставке ' + article}
            type='number'
            inputMode='numeric'
            min={0}
            max={2147483647}
            step={item.box_multiple ?? 1}
            disabled={disabled}
            {...form.register(`items.${index}.quantity`, {
              valueAsNumber: true,
              onChange: event => {
                if (item.variants?.length === 1)
                  form.setValue(
                    `items.${index}.variants.0.quantity`,
                    event.target.valueAsNumber,
                    { shouldDirty: true }
                  )
              }
            })}
          />
          <Button
            type='button'
            variant='ghost'
            size='sm'
            disabled={disabled}
            onClick={onRemove}
            aria-label={'Убрать ' + article}
          >
            Убрать
          </Button>
          <small className='text-destructive'>
            {form.formState.errors.items?.[index]?.quantity?.message}
          </small>
        </td>
      </tr>
      {hasVariants && open && (
        <tr className='supply-variant-details'>
          <td colSpan={4}>
            <PlanVariantFields
              item={item}
              index={index}
              form={form}
              disabled={disabled}
            />
          </td>
        </tr>
      )}
    </>
  )
}
