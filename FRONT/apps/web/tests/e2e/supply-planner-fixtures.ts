import type { Page } from '@playwright/test'

import { ozon, wb } from './fixtures'
import { mockSupplies } from './supplies-fixtures'

export async function mockPlanner(page: Page, role = 'owner') {
  const base = await mockSupplies(page, { role })
  const state = {
    base,
    requests: [] as URL[],
    writes: [] as { store: string; key: string; box_multiple: number }[],
    multiples: new Map<string, number>(),
    csrfValid: true,
    holdSave: false,
    releaseSave: null as (() => void) | null,
    failSave: false
  }
  await page.route('**/api/v1/**', async route => {
    const request = route.request(),
      url = new URL(request.url())
    const packaging = url.pathname.match(
      /\/stores\/([^/]+)\/inventory\/packaging\/([^/]+)$/
    )
    if (packaging) {
      const body = request.postDataJSON()
      state.csrfValid &&= request.headers()['x-csrf-token'] === 'pc_test'
      state.writes.push({
        store: packaging[1]!,
        key: packaging[2]!,
        box_multiple: body.box_multiple
      })
      if (state.failSave)
        return route.fulfill({
          status: 503,
          json: { detail: 'Не удалось сохранить кратность' }
        })
      state.multiples.set(packaging[1] + ':' + packaging[2], body.box_multiple)
      if (state.holdSave)
        await new Promise<void>(resolve => {
          state.releaseSave = resolve
        })
      return route.fulfill({
        json: { product_key: packaging[2], box_multiple: body.box_multiple }
      })
    }
    if (!url.pathname.includes('/inventory/replenishment'))
      return route.fallback()
    state.requests.push(url)
    const target = Number(url.searchParams.get('target_days') ?? 30),
      lead = Number(url.searchParams.get('lead_time_days') ?? 7)
    const store = url.searchParams.get('store_id'),
      limit = Number(url.searchParams.get('limit') ?? 3),
      offset = Number(url.searchParams.get('offset') ?? 0)
    const rows = (oz: boolean, count: number) =>
      Array.from({ length: count }, (_, index) => {
        const store_id = oz ? ozon : wb,
          id = 'product-' + index,
          raw = target * (oz ? 3 : 2) + index + 1
        const box_multiple = state.multiples.get(store_id + ':' + id) ?? 1
        return {
          id,
          marketplace: oz ? 'ozon' : 'wildberries',
          marketplace_code: (oz ? '900' : '100') + index,
          demand_basis: oz ? 'ozon_sales' : 'wb_orders',
          store_id,
          store_name: oz ? 'PERK Test Ozon' : 'PERK Test WB',
          nm_id: oz ? '' : '100' + index,
          vendor_code: (oz ? 'OZ-' : 'WB-') + index,
          title: (oz ? 'Мотоботы ' : 'Мотошлем ') + index,
          photo: null,
          colors: [],
          barcodes: ['000' + index],
          stock: 10,
          daily_orders: '2.5',
          days_of_stock: '4',
          required_quantity: raw,
          box_multiple,
          quantity: Math.ceil(raw / box_multiple) * box_multiple,
          urgent: index % 2 === 0
        }
      })
    const all =
      store === wb
        ? rows(false, 24)
        : store === ozon
          ? rows(true, 1)
          : [...rows(false, 24), ...rows(true, 1)]
    const items =
      url.searchParams.get('urgent_only') === 'true'
        ? all.filter(row => row.urgent)
        : all
    if (url.pathname.endsWith('/export'))
      return route.fulfill({
        contentType: 'text/csv; charset=utf-8',
        body:
          '\uFEFF"Кабинет";"Артикул";"Количество"\r\n' +
          items
            .map(
              row =>
                '"' +
                row.store_name +
                '";"' +
                row.vendor_code +
                '";"' +
                row.quantity +
                '"'
            )
            .join('\r\n')
      })
    return route.fulfill({
      json: {
        target_days: target,
        lead_time_days: lead,
        urgent_days: 7,
        recommended_units: all.reduce((sum, row) => sum + row.quantity, 0),
        product_count: all.length,
        urgent_count: all.filter(row => row.urgent).length,
        unknown_count: 0,
        no_orders_count: 0,
        partial: false,
        loading: false,
        stale: false,
        updated_at: null,
        count: items.length,
        limit,
        offset,
        items: limit ? items.slice(offset, offset + limit) : []
      }
    })
  })
  return state
}
