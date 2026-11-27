import { Decimal } from 'decimal.js'
import { z } from 'zod'

export const expenseCategories = [
  ['packaging', 'Упаковка'],
  ['fulfillment', 'Фулфилмент'],
  ['transport', 'Доставка'],
  ['advertising', 'Реклама'],
  ['rent', 'Аренда'],
  ['salary', 'Оплата труда'],
  ['other', 'Прочее']
] as const
export const taxRegimes = [
  ['none', 'Без расчёта налогов'],
  ['usn_income', 'УСН «Доходы»'],
  ['usn_income_expense', 'УСН «Доходы − расходы»'],
  ['profit', 'Налог на прибыль']
] as const
const rate = z
  .string()
  .trim()
  .regex(/^\d{1,3}(?:[.,]\d{1,2})?$/, 'Укажите процент')
  .refine(value => Number(value.replace(',', '.')) <= 100, 'Не больше 100%')
  .transform(value => value.replace(',', '.'))
export const expenseSchema = z.object({
  amount: z
    .string()
    .trim()
    .regex(/^\d{1,12}(?:[.,]\d{1,4})?$/, 'Укажите сумму, например 1500,50')
    .refine(value => {
      try {
        return new Decimal(value.replace(',', '.')).gt(0)
      } catch {
        return false
      }
    }, 'Сумма должна быть больше нуля')
    .transform(value => value.replace(',', '.')),
  expense_date: z.iso.date('Выберите дату'),
  comment: z
    .string()
    .trim()
    .min(1, 'Напишите, за что расход')
    .max(500, 'Не больше 500 символов'),
  custom_category: z
    .string()
    .trim()
    .max(100, 'Не больше 100 символов')
    .optional(),
  category: z.enum([
    'packaging',
    'fulfillment',
    'transport',
    'advertising',
    'rent',
    'salary',
    'other'
  ])
})
export type ExpenseValues = z.infer<typeof expenseSchema>
export const taxSchema = z
  .object({
    effective_from: z.iso.date('Выберите дату'),
    regime: z.enum(['none', 'usn_income', 'usn_income_expense', 'profit']),
    rate,
    vat_rate: rate,
    income_base: z.enum(['revenue', 'payout'])
  })
  .superRefine((value, context) => {
    if (
      value.regime === 'none' &&
      (Number(value.rate) !== 0 || Number(value.vat_rate) !== 0)
    )
      context.addIssue({
        code: 'custom',
        path: ['rate'],
        message: 'Для отключённого расчёта укажите нулевые ставки'
      })
  })
export type TaxValues = z.infer<typeof taxSchema>
