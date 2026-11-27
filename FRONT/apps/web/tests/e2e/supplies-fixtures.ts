import type { Page } from '@playwright/test'

import type {
  ReplenishmentItem,
  ReplenishmentOverview,
  SupplyCard,
  SupplyList
} from '@app/api'

import { mockApi, ozon, wb } from './fixtures'

function recommendation(index: number, oz = false): ReplenishmentItem {
  return {
    id: `product-${index}`,
    marketplace: oz ? 'ozon' : 'wildberries',
    marketplace_code: oz ? `90010${index}` : `10${index}`,
    demand_basis: oz ? 'ozon_sales' : 'wb_orders',
    store_id: oz ? ozon : wb,
    store_name: oz ? 'PERK Test Ozon' : 'PERK Test WB',
    nm_id: oz ? '' : `10${index}`,
    vendor_code: `${oz ? 'OZ' : 'WB'}-${index}`,
    title:
      index === 0
        ? oz
          ? 'Мотоботы Track'
          : 'Мотошлем Trail'
        : `Модель ${index}`,
    photo: index === 0 ? 'https://supply-test.local/product.svg' : null,
    colors: ['чёрный'],
    barcodes: [`00010${index}`],
    stock: 10 + index,
    daily_orders: '2.5',
    days_of_stock: index % 3 === 0 ? '5' : '15',
    quantity: 150 + index,
    urgent: index % 3 === 0
  }
}
function supply(index: number, oz = false): SupplyCard {
  return {
    marketplace: oz ? 'ozon' : 'wildberries',
    external_id: `${oz ? 'oz' : 'wb'}:${index}`,
    display_number: oz ? 'ОЗ-001' : '',
    supply_id: oz ? null : String(101 + index),
    preorder_id: oz ? '9001' : null,
    status: oz
      ? 'accepting'
      : index === 1
        ? 'accepted'
        : index === 2
          ? 'unknown'
          : 'ready_to_ship',
    rejected: !oz && index === 1,
    planned_date: index === 2 ? null : '2026-11-06',
    actual_date: index === 1 ? '2026-11-07' : null,
    created_date: '2026-11-01',
    destination: oz ? 'Москва и МО' : 'Коледино',
    quantity: index === 0 ? null : 150,
    accepted_quantity: index === 0 ? 0 : null,
    store_id: oz ? ozon : wb,
    store_name: oz ? 'PERK Test Ozon' : 'PERK Test WB'
  }
}
export async function mockSupplies(
  page: Page,
  options: {
    role?: string
    empty?: boolean
    noData?: boolean
    historyOnly?: boolean
  } = {}
) {
  await mockApi(page, { role: options.role ?? 'owner' })
  const state = {
    requests: [] as URL[],
    methods: [] as string[],
    loading: false,
    missingAccess: false,
    incomplete: false,
    fail: false
  }
  await page.route('https://supply-test.local/**', route =>
    route.fulfill({
      contentType: 'image/svg+xml',
      body: '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="400"><rect width="300" height="400" fill="#e4e1fa"/><circle cx="150" cy="150" r="80" fill="#aaa1ff"/><text x="80" y="300" font-size="24" fill="#26243a">PERK TEST</text></svg>'
    })
  )
  await page.route('**/api/v1/**', async route => {
    const request = route.request(),
      url = new URL(request.url())
    if (options.historyOnly && url.pathname.endsWith('/stores'))
      return route.fulfill({
        json: [
          {
            id: wb,
            name: 'PERK Test WB',
            marketplace: 'wildberries',
            connection_status: 'connected',
            reports_available: true,
            features: ['catalog', 'supply_history']
          }
        ]
      })
    const rec = url.pathname.endsWith('/inventory/replenishment'),
      history = url.pathname.endsWith('/inventory/supplies')
    if (!rec && !history) return route.fallback()
    state.requests.push(url)
    state.methods.push(request.method())
    if (state.fail)
      return route.fulfill({
        status: 503,
        json: { detail: 'Не удалось загрузить поставки' }
      })
    const store = url.searchParams.get('store_id'),
      limit = Number(url.searchParams.get('limit') ?? 3),
      offset = Number(url.searchParams.get('offset') ?? 0)
    if (rec) {
      let items =
        options.empty || options.noData
          ? []
          : store === wb
            ? Array.from({ length: 24 }, (_, i) => recommendation(i))
            : store === ozon
              ? [recommendation(0, true)]
              : [
                  ...Array.from({ length: 24 }, (_, i) => recommendation(i)),
                  recommendation(0, true)
                ]
      if (url.searchParams.get('urgent_only') === 'true')
        items = items.filter(item => item.urgent)
      const data: ReplenishmentOverview = {
        target_days: 30,
        lead_time_days: 7,
        urgent_days: 7,
        recommended_units: options.noData
          ? null
          : options.empty
            ? 0
            : store === wb
              ? 500
              : store === ozon
                ? 900
                : 1400,
        product_count: options.noData
          ? null
          : options.empty
            ? 0
            : store === wb
              ? 24
              : store === ozon
                ? 1
                : 25,
        urgent_count: options.noData
          ? null
          : options.empty
            ? 0
            : store === wb
              ? 8
              : store === ozon
                ? 1
                : 9,
        unknown_count: options.noData ? 5 : 0,
        no_orders_count: 0,
        partial: !!options.noData,
        loading: state.loading,
        stale: false,
        updated_at: null,
        items: limit ? items.slice(offset, offset + limit) : [],
        count: items.length,
        limit,
        offset
      }
      return route.fulfill({ json: data })
    }
    const items =
      options.empty || state.missingAccess || state.incomplete
        ? []
        : store === wb
          ? Array.from({ length: 24 }, (_, i) => supply(i))
          : store === ozon
            ? [supply(0, true)]
            : [
                ...Array.from({ length: 24 }, (_, i) => supply(i)),
                supply(0, true)
              ]
    const data: SupplyList = {
      items: limit ? items.slice(offset, offset + limit) : [],
      count: items.length,
      limit,
      offset,
      loading: state.loading,
      incomplete: state.incomplete,
      missing_access: state.missingAccess,
      updated_at: null,
      stale: false
    }
    return route.fulfill({ json: data })
  })
  return state
}
