import { z } from 'zod'

export const costSchema = z.object({
  amount: z
    .string()
    .trim()
    .regex(/^\d{1,12}(?:[.,]\d{1,4})?$/, 'Укажите цену, например 450,50'),
  effective_from: z.iso.date('Укажите дату в формате ГГГГ-ММ-ДД'),
  barcode: z.string()
})
