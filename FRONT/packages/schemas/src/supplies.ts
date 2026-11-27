import {
  InventoryPackagingSaveBody,
  InventoryReplenishmentQueryParams,
  SupplyPlanCreateBody,
  SupplyPlanSaveBody
} from '@app/api/zod'
import { z } from 'zod'

const wholeDays = (value: number) => Number.isInteger(value)
export const supplyParametersSchema = InventoryReplenishmentQueryParams.pick({
  include_fbs: true,
  target_days: true,
  lead_time_days: true
}).extend({
  target_days: InventoryReplenishmentQueryParams.shape.target_days.refine(
    wholeDays,
    'Введите целое число дней'
  ),
  lead_time_days: InventoryReplenishmentQueryParams.shape.lead_time_days.refine(
    wholeDays,
    'Введите целое число дней'
  )
})
export const supplyPackagingSchema = InventoryPackagingSaveBody.extend({
  box_multiple: InventoryPackagingSaveBody.shape.box_multiple.int(
    'Введите целое количество'
  )
})
export const supplyPlanCreateSchema = SupplyPlanCreateBody.extend({
  title: SupplyPlanCreateBody.shape.title.trim().min(1, 'Введите название'),
  destination: SupplyPlanCreateBody.shape.destination.removeDefault().trim(),
  store_id: z.uuid('Выберите кабинет')
})
export function supplyPlanUpdateSchema(
  items: {
    product_key: string
    box_multiple?: number
    variants?: { variant_id: string; barcodes: string[] }[]
  }[]
) {
  const products = new Map(items.map(item => [item.product_key, item]))
  return SupplyPlanSaveBody.extend({
    title: SupplyPlanSaveBody.shape.title.trim().min(1, 'Введите название'),
    destination: SupplyPlanSaveBody.shape.destination.removeDefault().trim()
  }).superRefine((data, ctx) => {
    data.items.forEach((item, index) => {
      const product = products.get(item.product_key)
      const multiple = product?.box_multiple ?? 1
      if (item.variants) {
        const variants = product?.variants ?? []
        const choices = new Map(variants.map(row => [row.variant_id, row]))
        if (
          item.variants.reduce((sum, row) => sum + row.quantity, 0) >
          item.quantity
        )
          ctx.addIssue({
            code: 'custom',
            path: ['items', index, 'quantity'],
            message: 'По размерам указано больше, чем к поставке'
          })
        item.variants.forEach((row, position) => {
          if (
            row.barcode &&
            !choices.get(row.variant_id)?.barcodes.includes(row.barcode)
          )
            ctx.addIssue({
              code: 'custom',
              path: ['items', index, 'variants', position, 'barcode'],
              message: 'Выберите штрихкод этого размера'
            })
        })
      }
      if (item.quantity % multiple !== 0)
        ctx.addIssue({
          code: 'custom',
          path: ['items', index, 'quantity'],
          message: 'Кратно ' + multiple
        })
    })
    if (data.status === 'ready' && !data.items.some(item => item.quantity > 0))
      ctx.addIssue({
        code: 'custom',
        path: ['status'],
        message: 'Укажите количество товаров'
      })
  })
}
export type SupplyPlanFormValues = z.input<
  ReturnType<typeof supplyPlanUpdateSchema>
>
export type SupplyPlanValues = z.output<
  ReturnType<typeof supplyPlanUpdateSchema>
>
export type SupplyParameters = z.output<typeof supplyParametersSchema>
