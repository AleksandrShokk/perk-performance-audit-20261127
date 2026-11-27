import type { UseFormReturn } from 'react-hook-form'

import type { SupplyPlanFormValues, SupplyPlanValues } from '@app/schemas'

import type { PlanView } from '@app/api'

export type PlanFormApi = UseFormReturn<
  SupplyPlanFormValues,
  unknown,
  SupplyPlanValues
>

export const planStatuses = {
  draft: 'Черновик',
  ready: 'Готов',
  archived: 'Архив'
} as const
export function planValues(plan: PlanView): SupplyPlanFormValues {
  return {
    revision: plan.revision,
    title: plan.title,
    destination: plan.destination,
    status: plan.status,
    items: plan.items.map(item => ({
      product_key: item.product_key,
      quantity: item.quantity,
      ...(item.variants?.length
        ? {
            variants: item.variants.map(row => ({
              variant_id: row.variant_id,
              quantity: row.quantity ?? 0,
              barcode: row.barcode ?? ''
            }))
          }
        : {})
    }))
  }
}
export function matchingPlanItems(plan: PlanView, search: string) {
  const needle = search.trim().toLocaleLowerCase('ru-RU')
  return plan.items
    .map((item, index) => ({ item, index }))
    .filter(
      ({ item }) =>
        !needle ||
        [
          item.title,
          item.vendor_code,
          item.marketplace_code,
          item.nm_id,
          ...item.barcodes,
          ...(item.variants ?? []).flatMap(row => [row.size, ...row.barcodes])
        ]
          .join(' ')
          .toLocaleLowerCase('ru-RU')
          .includes(needle)
    )
}
