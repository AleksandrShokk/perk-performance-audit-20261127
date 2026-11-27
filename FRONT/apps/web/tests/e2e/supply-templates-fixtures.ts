import type { Page } from '@playwright/test'

import type { PlanView, TemplateInspection } from '@app/api'

import { mockPlans } from './supply-plans-fixtures'

function inspection(plan: PlanView): TemplateInspection {
  const kinds =
    plan.marketplace === 'ozon'
      ? (['barcode', 'vendor_code', 'fbo_sku'] as const)
      : (['barcode'] as const)
  return {
    digest: 'a'.repeat(64),
    revision: plan.revision,
    sheets: [
      {
        name: 'Поставка',
        headers: [
          {
            row: 1,
            columns: [
              { key: 'A', label: 'Баркод' },
              { key: 'B', label: 'Количество' }
            ]
          }
        ]
      },
      {
        name: 'Другой лист',
        headers: [
          {
            row: 3,
            columns: [
              { key: 'D', label: 'Артикул' },
              { key: 'G', label: 'Количество' }
            ]
          }
        ]
      }
    ],
    choices: kinds.map((value, index) => ({
      value,
      label: {
        barcode: 'Штрихкод',
        vendor_code: 'Артикул продавца',
        fbo_sku: 'SKU Ozon FBO'
      }[value],
      count: plan.product_count,
      units: plan.quantity,
      data_digest: String(index + 1).repeat(64),
      error: null,
      preview: plan.items
        .slice(0, 3)
        .map((item, i) => ({
          identifier:
            value === 'barcode'
              ? item.barcodes[0]!
              : value === 'vendor_code'
                ? item.vendor_code
                : String(101 + i),
          quantity: item.quantity
        }))
    })),
    suggested: {
      sheet: 'Поставка',
      header_row: 1,
      first_row: 2,
      identifier_column: 'A',
      quantity_column: 'B',
      identifier_type: 'barcode',
      mode: 'append'
    }
  }
}
export async function mockTemplates(page: Page, role = 'owner') {
  const plans = await mockPlans(page, role)
  const state = {
    plans,
    inspectCalls: 0,
    fills: [] as URL[],
    csrfValid: true,
    failFill: false,
    hold: false,
    release: null as (() => void) | null
  }
  await page.route('**/api/v1/**/template/*', async route => {
    const req = route.request(),
      url = new URL(req.url())
    state.csrfValid &&= req.headers()['x-csrf-token'] === 'pc_test'
    const id = url.pathname.split('/template/')[0]!.split('/').at(-1)!
    const plan = plans.plans.find(plan => plan.id === id)!
    if (url.pathname.endsWith('/inspect')) {
      state.inspectCalls++
      return route.fulfill({ json: inspection(plan) })
    }
    state.fills.push(url)
    if (state.hold)
      await new Promise<void>(resolve => {
        state.release = resolve
      })
    if (state.failFill)
      return route.fulfill({
        status: 409,
        contentType: 'application/json',
        body: JSON.stringify({
          detail: 'План изменился. Вернитесь к нему и загрузите шаблон заново.'
        })
      })
    return route.fulfill({
      contentType:
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      body: Buffer.from('PK-test-filled-workbook')
    })
  })
  return state
}
