import { SupplyTemplateFillQueryParams } from '@app/api/zod'
import type { z } from 'zod'

export const supplyTemplateMappingSchema = SupplyTemplateFillQueryParams.omit({
  revision: true,
  digest: true,
  data_digest: true
}).superRefine((value, ctx) => {
  if (value.identifier_column === value.quantity_column)
    ctx.addIssue({
      code: 'custom',
      path: ['quantity_column'],
      message: 'Выберите другой столбец'
    })
  if (value.first_row <= value.header_row)
    ctx.addIssue({
      code: 'custom',
      path: ['first_row'],
      message: 'Товары должны идти после заголовка'
    })
})
export type SupplyTemplateMappingInput = z.input<
  typeof supplyTemplateMappingSchema
>
export type SupplyTemplateMapping = z.output<typeof supplyTemplateMappingSchema>
