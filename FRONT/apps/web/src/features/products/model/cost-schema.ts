import { z } from 'zod'

export const costSchema = z.object({
  amount: z
    .string()
    .trim()
    .regex(/^\d{1,12}(?:[.,]\d{1,4})?$/, 'Укажите цену, например 1250,50')
    .transform(value => value.replace(',', '.')),
  effective_from: z.iso.date('Выберите дату'),
  barcode: z.string().max(100)
})
export type CostValues = z.infer<typeof costSchema>
