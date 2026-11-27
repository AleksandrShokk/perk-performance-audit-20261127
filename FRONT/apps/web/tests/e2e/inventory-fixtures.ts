import type { Page } from '@playwright/test'

import type {
  InventoryAmounts,
  InventoryOverview,
  InventoryPosition,
  ProductVariant
} from '@app/api'

import { mockApi, ozon, wb } from './fixtures'

function amounts(units: number | null, value?: string): InventoryAmounts {
  return {
    units,
    retail_value: units == null ? null : (value ?? String(units * 1000)),
    retail_complete: units != null,
    cost_value: units == null ? null : String(units * 400),
    cost_complete: units != null,
    stale: false,
    updated_at: '2026-11-06T09:00:00Z'
  }
}
function variant(
  id: string,
  size: string,
  quantity: number,
  oz = false
): ProductVariant {
  return {
    id: `uuid-${id}`,
    chrt_id: oz ? '' : id,
    external_id: oz ? id : undefined,
    size,
    barcodes: [`000${id}`],
    stock: quantity,
    to_client: null,
    from_client: null,
    unit_cost: '400',
    warehouses: oz
      ? []
      : [{ name: size === 'M' ? 'Коледино' : 'Казань', quantity }]
  }
}
function position(index: number, oz = false): InventoryPosition {
  const id = String((oz ? 900101 : 101) + index)
  const variants = [variant(id, 'M', 4, oz), variant(`${id}2`, 'L', 3, oz)]
  return {
    product: {
      id: `${oz ? 'oz' : 'wb'}-${id}`,
      store_id: oz ? ozon : wb,
      store_name: oz ? 'PERK Test Ozon' : 'PERK Test WB',
      marketplace: oz ? 'ozon' : 'wildberries',
      nm_id: oz ? '' : id,
      marketplace_code: id,
      vendor_code: `${oz ? 'OZ-' : 'WB-'}${id}`,
      title: oz
        ? 'Мотоботы Track'
        : index === 0
          ? 'Мотошлем Trail'
          : `Модель ${index}`,
      brand: 'PERK Test',
      subject: 'Экипировка',
      colors: ['чёрный'],
      photos:
        index === 0
          ? [
              'https://inventory-test.local/front.svg',
              'https://inventory-test.local/back.svg'
            ]
          : [],
      variants,
      stock: 7,
      stock_updated_at: '2026-11-06T09:00:00Z',
      stock_stale: false,
      missing_cost_variants: 0
    },
    fbo: amounts(index === 1 ? 0 : 7),
    fbs: amounts(3),
    fbs_sizes: variants.map((variant, i) => ({
      variant_id: variant.id,
      chrt_id: variant.chrt_id,
      quantity: i === 0 ? 2 : 1,
      warehouses: oz
        ? {}
        : { [i === 0 ? 'Склад Восток' : 'Склад Запад']: i === 0 ? 2 : 1 }
    })),
    turnover_basis: oz ? 'ozon_sales_28d_fbo' : 'wb_orders_28d',
    turnover_days: oz || index === 1 ? null : '23.5',
    turnover_status: oz ? 'no_sales' : index === 1 ? 'no_orders' : 'ready'
  }
}
export async function mockInventory(
  page: Page,
  options: {
    role?: string
    canCost?: boolean
    mode?: 'separate' | 'shared' | 'unknown'
    error?: boolean
    empty?: boolean
    loading?: boolean
  } = {}
) {
  await mockApi(page, { role: options.role ?? 'owner' })
  const state = {
    requests: [] as URL[],
    writes: [] as { mode: string; csrf?: string }[],
    mode: options.mode ?? 'separate',
    delaySave: false,
    loading: options.loading ?? false,
    error: options.error ?? false,
    canCost: options.canCost ?? options.role !== 'viewer'
  }
  await page.route('https://inventory-test.local/**', route =>
    route.fulfill({
      contentType: 'image/svg+xml',
      body: '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="400"><rect width="300" height="400" fill="#e4e1fa"/><circle cx="150" cy="160" r="80" fill="#aaa1ff"/><text x="70" y="300" fill="#26243a" font-size="24">PERK TEST</text></svg>'
    })
  )
  await page.route('**/api/v1/**', async route => {
    const request = route.request()
    const url = new URL(request.url())
    if (url.pathname.endsWith('/inventory/settings')) {
      if (request.method() === 'PUT') {
        const body = request.postDataJSON()
        state.writes.push({
          mode: body.fbs_mode,
          csrf: request.headers()['x-csrf-token']
        })
        if (state.delaySave)
          await new Promise(resolve => setTimeout(resolve, 800))
        state.mode = body.fbs_mode
      }
      return route.fulfill({ json: { fbs_mode: state.mode } })
    }
    if (!url.pathname.endsWith('/inventory/overview')) return route.fallback()
    state.requests.push(url)
    if (state.error)
      return route.fulfill({
        status: 503,
        json: { detail: 'Inventory unavailable' }
      })
    const store = url.searchParams.get('store_id')
    const limit = Number(url.searchParams.get('limit') ?? 0)
    const offset = Number(url.searchParams.get('offset') ?? 0)
    const q = url.searchParams.get('q') ?? ''
    let items = options.empty
      ? []
      : store === ozon
        ? [position(0, true)]
        : store === wb
          ? Array.from({ length: 22 }, (_, i) => position(i))
          : [
              ...Array.from({ length: 22 }, (_, i) => position(i)),
              position(0, true)
            ]
    if (q)
      items = items.filter(item =>
        `${item.product.title} ${item.product.vendor_code} ${item.product.variants.flatMap(row => row.barcodes).join(' ')}`
          .toLowerCase()
          .includes(q.toLowerCase())
      )
    const all = !store
    const data: InventoryOverview = {
      fbo: amounts(
        all ? 300 : store === ozon ? 200 : 100,
        all ? '300500.25' : store === ozon ? '200000' : '100500.25'
      ),
      fbs: amounts(
        all && state.mode !== 'separate'
          ? null
          : all
            ? 50
            : store === ozon
              ? 30
              : 20
      ),
      total: amounts(
        all && state.mode !== 'separate'
          ? null
          : all
            ? 350
            : store === ozon
              ? 230
              : 120
      ),
      turnover_basis: all
        ? 'mixed'
        : store === ozon
          ? 'ozon_sales_28d_fbo'
          : 'wb_orders_28d',
      turnover_supported: !all,
      turnover_days: all ? null : store === ozon ? '18.2' : '23.5',
      aggregation_status:
        all && state.mode !== 'separate'
          ? 'warehouse_mapping_required'
          : 'ready',
      count: items.length,
      limit,
      offset,
      currency: 'RUB',
      can_cost: state.canCost,
      is_loading: state.loading,
      turnover_loading: state.loading,
      missing_sources: [],
      items: limit ? items.slice(offset, offset + limit) : []
    }
    // Summary changes with filters in the real API: the page must not reuse it.
    if (q) {
      data.fbo = amounts(1, '999')
      data.fbs = amounts(0)
    }
    return route.fulfill({ json: data })
  })
  return state
}
