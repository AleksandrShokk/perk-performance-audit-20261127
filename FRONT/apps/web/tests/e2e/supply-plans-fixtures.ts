import type { Page } from '@playwright/test'

import type { PlanCreate, PlanUpdate, PlanView } from '@app/api'

import { ozon, wb } from './fixtures'
import { mockPlanner } from './supply-planner-fixtures'

function makePlan(store: string, index: number, input: PlanCreate): PlanView {
  const oz = store === ozon
  const items = Array.from({ length: oz ? 1 : 24 }, (_, i) => ({
    id: 'product-' + i,
    product_key: 'product-' + i,
    marketplace: oz ? 'ozon' : 'wildberries',
    marketplace_code: (oz ? '900' : '100') + i,
    demand_basis: oz ? ('ozon_sales' as const) : ('wb_orders' as const),
    store_id: store,
    store_name: oz ? 'PERK Test Ozon' : 'PERK Test WB',
    nm_id: oz ? '' : '100' + i,
    vendor_code: (oz ? 'OZ-' : 'WB-') + i,
    title: (oz ? 'Мотоботы ' : 'Мотошлем ') + i,
    photo: null,
    colors: [],
    barcodes: ['000' + i],
    stock: 10,
    daily_orders: '2.5',
    days_of_stock: '4',
    quantity: 65 + i * 5,
    recommended_quantity: 65 + i * 5,
    box_multiple: 5,
    required_quantity: 61 + i * 5,
    urgent: i % 2 === 0,
    variants: [
      {
        variant_id: 'size-' + i,
        external_id: String(i),
        size: 'M',
        barcodes: ['000' + i],
        barcode: '000' + i,
        quantity: 65 + i * 5
      }
    ]
  })).filter(item => !input.urgent_only || item.urgent)
  return {
    id: '40000000-0000-4000-8000-' + String(index).padStart(12, '0'),
    store_id: store,
    store_name: items[0]!.store_name,
    marketplace: oz ? 'ozon' : 'wildberries',
    title: input.title,
    destination: input.destination ?? '',
    destination_id: input.destination_id,
    status: 'draft',
    revision: 1,
    quantity: items.reduce((sum, row) => sum + row.quantity, 0),
    product_count: items.length,
    allocated_quantity: items.reduce((sum, row) => sum + row.quantity, 0),
    allocation_complete: true,
    allocation_error: null,
    created_at: '2026-11-06T10:00:00Z',
    updated_at: '2026-11-06T10:00:00Z',
    target_days: input.target_days ?? 30,
    lead_time_days: input.lead_time_days ?? 7,
    source_updated_at: '2026-11-06T09:00:00Z',
    source_partial: false,
    items
  }
}

function syncAllocation(plan: PlanView) {
  const used = new Set<string>()
  plan.allocated_quantity = 0
  plan.allocation_error = null
  for (const item of plan.items) {
    const allocated = (item.variants ?? []).reduce(
      (sum, row) => sum + (row.quantity ?? 0),
      0
    )
    plan.allocated_quantity += allocated
    if (allocated !== item.quantity)
      plan.allocation_error = 'Распределите количество по размерам'
    for (const row of item.variants ?? []) {
      if (!row.quantity) continue
      if (!row.barcode || !row.barcodes.includes(row.barcode))
        plan.allocation_error = 'Выберите штрихкод'
      else if (used.has(row.barcode))
        plan.allocation_error = 'Штрихкод используется в нескольких позициях'
      used.add(row.barcode ?? '')
    }
  }
  plan.allocation_complete = plan.quantity > 0 && !plan.allocation_error
}

export async function mockPlans(page: Page, role = 'owner') {
  await mockPlanner(page, role)
  const state = {
    plans: [] as PlanView[],
    writes: [] as PlanUpdate[],
    creates: [] as { store: string; data: PlanCreate }[],
    csrfValid: true,
    conflict: false,
    fail: false,
    hold: false,
    release: null as (() => void) | null,
    seed: (store = wb, title = 'План на ноябрь') => {
      const plan = makePlan(store, state.plans.length + 1, { title })
      state.plans.push(plan)
      return plan
    }
  }
  await page.route('**/api/v1/**', async route => {
    const req = route.request(),
      url = new URL(req.url())
    const create = url.pathname.match(/\/stores\/([^/]+)\/inventory\/plans$/)
    if (create && req.method() === 'POST') {
      const data = req.postDataJSON() as PlanCreate
      state.csrfValid &&= req.headers()['x-csrf-token'] === 'pc_test'
      state.creates.push({ store: create[1]!, data })
      const plan = makePlan(create[1]!, state.plans.length + 1, data)
      plan.items = []
      plan.quantity = 0
      plan.product_count = 0
      plan.allocated_quantity = 0
      plan.allocation_complete = false
      state.plans.unshift(plan)
      return route.fulfill({ status: 201, json: plan })
    }
    const match = url.pathname.match(
      /\/inventory\/plans(?:\/([^/]+))?(?:\/(export|items-export|variants|products|import))?$/
    )
    if (!match) return route.fallback()
    if (!match[1]) {
      const store = url.searchParams.get('store_id'),
        limit = Number(url.searchParams.get('limit') ?? 20),
        offset = Number(url.searchParams.get('offset') ?? 0)
      const plans = state.plans.filter(
        plan => !store || plan.store_id === store
      )
      return route.fulfill({
        json: {
          items: plans.slice(offset, offset + limit),
          count: plans.length,
          limit,
          offset
        }
      })
    }
    const plan = state.plans.find(plan => plan.id === match[1])
    if (!plan)
      return route.fulfill({ status: 404, json: { detail: 'План не найден' } })
    if (req.method() === 'DELETE') {
      state.csrfValid &&= req.headers()['x-csrf-token'] === 'pc_test'
      state.plans = state.plans.filter(row => row.id !== plan.id)
      return route.fulfill({ status: 204 })
    }
    if (match[2] === 'import')
      return route.fulfill({
        status: 422,
        json: {
          detail:
            'В кабинете не найдены товары из файла: 1. строка 2: CHOHO_525SX2_120L_GOLD.'
        }
      })
    if (match[2] === 'products') {
      const catalogue = makePlan(plan.store_id, 999, { title: 'Каталог' }).items
      if (req.method() === 'GET') {
        const needle = (url.searchParams.get('query') ?? '').toLowerCase()
        const offset = Number(url.searchParams.get('offset') ?? 0)
        const limit = Number(url.searchParams.get('limit') ?? 20)
        const rows = catalogue.filter(
          item =>
            !plan.items.some(row => row.product_key === item.product_key) &&
            (!needle ||
              (item.title + ' ' + item.vendor_code)
                .toLowerCase()
                .includes(needle))
        )
        return route.fulfill({
          json: {
            items: rows.slice(offset, offset + limit),
            count: rows.length
          }
        })
      }
      const input = req.postDataJSON() as { product_keys: string[] }
      state.csrfValid &&= req.headers()['x-csrf-token'] === 'pc_test'
      plan.items.push(
        ...catalogue
          .filter(item => input.product_keys.includes(item.product_key))
          .map(item => ({
            ...item,
            quantity: 0,
            variants: item.variants?.map(v => ({ ...v, quantity: 0 }))
          }))
      )
      plan.revision++
      return route.fulfill({ json: plan })
    }
    if (match[2] === 'variants') {
      state.csrfValid &&= req.headers()['x-csrf-token'] === 'pc_test'
      for (const item of plan.items)
        if (!item.variants?.length)
          item.variants = [
            {
              variant_id: 'loaded-' + item.product_key,
              external_id: item.product_key,
              size: 'M',
              barcodes: ['000' + item.product_key],
              barcode: '000' + item.product_key,
              quantity: item.quantity
            }
          ]
      plan.revision++
      syncAllocation(plan)
      return route.fulfill({ json: plan })
    }
    syncAllocation(plan)
    if (match[2] === 'items-export') {
      if (!plan.allocation_complete)
        return route.fulfill({
          status: 409,
          json: { detail: plan.allocation_error }
        })
      return route.fulfill({
        contentType: 'text/csv; charset=utf-8',
        body:
          '\ufeff"Штрихкод";"Количество, шт."\r\n' +
          plan.items
            .flatMap(item =>
              (item.variants ?? [])
                .filter(row => row.quantity)
                .map(row => `"'${row.barcode}";"${row.quantity}"`)
            )
            .join('\r\n')
      })
    }
    if (match[2] === 'export')
      return route.fulfill({
        contentType: 'text/csv; charset=utf-8',
        body:
          '\ufeff"План";"Товар";"Количество"\r\n' +
          plan.items
            .filter(row => row.quantity)
            .map(
              row => `"${plan.title}";"${row.vendor_code}";"${row.quantity}"`
            )
            .join('\r\n')
      })
    if (req.method() !== 'PUT') return route.fulfill({ json: plan })
    const data = req.postDataJSON() as PlanUpdate
    state.csrfValid &&= req.headers()['x-csrf-token'] === 'pc_test'
    state.writes.push(data)
    if (state.hold)
      await new Promise<void>(resolve => {
        state.release = resolve
      })
    if (state.conflict || data.revision !== plan.revision)
      return route.fulfill({
        status: 409,
        json: { detail: 'План уже изменён. Закройте его и откройте заново.' }
      })
    if (state.fail)
      return route.fulfill({
        status: 503,
        json: { detail: 'Не удалось сохранить план' }
      })
    plan.title = data.title
    plan.destination = data.destination ?? ''
    plan.status = data.status ?? 'draft'
    plan.revision++
    plan.items = plan.items
      .filter(item =>
        data.items.some(row => row.product_key === item.product_key)
      )
      .map(item => ({
        ...item,
        quantity: data.items.find(row => row.product_key === item.product_key)!
          .quantity,
        variants: (item.variants ?? []).map(variant => {
          const input = data.items.find(
            row => row.product_key === item.product_key
          )!
          const value = input.variants?.find(
            row => row.variant_id === variant.variant_id
          )
          return value
            ? { ...variant, ...value }
            : item.variants?.length === 1
              ? { ...variant, quantity: input.quantity }
              : variant
        })
      }))
    plan.quantity = plan.items.reduce((sum, row) => sum + row.quantity, 0)
    plan.product_count = plan.items.filter(row => row.quantity > 0).length
    return route.fulfill({ json: plan })
  })
  return state
}
