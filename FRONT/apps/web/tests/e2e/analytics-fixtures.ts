import { HISTORY_START, eachDay, lastDays } from '@app/analytics/dates'
import { previousPeriod } from '@app/analytics/sales'
import type { Page } from '@playwright/test'

import type {
  FunnelFigures,
  FunnelProduct,
  FunnelReport,
  FunnelSummaryReport
} from '@app/api'

import { mockApi, ozon, wid } from './fixtures'

export function figures(units: number, traffic = true): FunnelFigures {
  return {
    opens: traffic ? units * 100 : null,
    carts: traffic ? units * 20 : null,
    orders: units * 5,
    buyouts: units * 4,
    cancellations: units,
    wishlist: null,
    orders_amount: String(units * 5000),
    buyouts_amount: String(units * 4000),
    cancellations_amount: String(units * 1000),
    add_to_cart_percent: traffic ? '20' : null,
    cart_to_order_percent: traffic ? '25' : null,
    open_to_order_percent: traffic ? '5' : null,
    buyout_percent: '80'
  }
}
const unknown = (): FunnelFigures => ({
  opens: null,
  carts: null,
  orders: null,
  buyouts: null,
  cancellations: null,
  wishlist: null,
  orders_amount: null,
  buyouts_amount: null,
  cancellations_amount: null,
  add_to_cart_percent: null,
  cart_to_order_percent: null,
  open_to_order_percent: null,
  buyout_percent: null
})
export async function mockAnalytics(
  page: Page,
  options: {
    twoOzon?: boolean
    analyticsOnly?: boolean
    forbidden?: boolean
    ozonCurrency?: string
    truncated?: boolean
    empty?: boolean
  } = {}
) {
  await mockApi(page, { role: options.forbidden ? 'viewer' : 'owner' })
  const state = {
    requests: [] as URL[],
    catalogRequests: 0,
    partial: false,
    summaryReady: true,
    partialAmounts: false,
    fail: false
  }
  await page.route('https://analytics-test.local/**', route =>
    route.fulfill({
      contentType: 'image/svg+xml',
      body: '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="400"><rect width="300" height="400" fill="#e4e1fa"/><circle cx="150" cy="150" r="80" fill="#aaa1ff"/><text x="70" y="300" font-size="24" fill="#26243a">PERK TEST</text></svg>'
    })
  )
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url())
    if (options.analyticsOnly && url.pathname === '/api/v1/workspaces')
      return route.fulfill({
        json: [
          {
            id: wid,
            name: 'PERK Test',
            role: 'manager',
            permissions: ['analytics.read'],
            store_ids: null
          }
        ]
      })
    if (
      url.pathname.endsWith('/products') ||
      url.pathname.endsWith('/product-models')
    )
      state.catalogRequests++
    if (!url.pathname.includes('/insights/funnel')) return route.fallback()
    if (url.pathname.endsWith('/availability'))
      return route.fulfill({
        json: { date_from: HISTORY_START, date_to: lastDays(1).date_to }
      })
    state.requests.push(url)
    if (state.fail)
      return route.fulfill({
        status: 503,
        json: { detail: 'Не удалось загрузить аналитику' }
      })
    const isOzon = url.pathname.includes(ozon)
    const range = {
      date_from: url.searchParams.get('date_from') ?? lastDays(7).date_from,
      date_to: url.searchParams.get('date_to') ?? lastDays(7).date_to
    }
    const days = eachDay(range),
      past = range.date_to < lastDays(1).date_to
    const factor = past ? 0.8 : 1,
      traffic = !isOzon,
      currency = isOzon ? (options.ozonCurrency ?? 'RUB') : 'RUB'
    const basis = isOzon ? (options.twoOzon ? 470 : 240) : 1500
    const noData = !!options.empty
    const known = noData ? 0 : state.partial && !past ? 1 : days.length
    if (url.pathname.endsWith('/progress'))
      return route.fulfill({
        json: {
          revision: `${known}-${state.summaryReady}`,
          known_days: known,
          available_days: days.length,
          is_loading: state.partial && !past,
          records_processed: known * basis,
          pages_processed: known,
          next_attempt_at: null,
          error_code: null
        }
      })
    const totals = noData ? unknown() : figures(basis * factor * known, traffic)
    const partial_amounts = state.partialAmounts ? ['orders_amount'] : []
    const freshness = {
      computed_at: '2026-11-06T12:00:00Z',
      stale: state.partial && !past
    }
    if (url.pathname.endsWith('/summary')) {
      const ready = !noData && state.summaryReady
      const data: FunnelSummaryReport = {
        ...range,
        status: ready ? 'ready' : 'preparing',
        currency,
        totals: ready ? figures(basis * days.length, traffic) : unknown(),
        partial_amounts,
        previous: {
          ...previousPeriod(range),
          totals: ready
            ? figures(basis * days.length * 0.8, traffic)
            : unknown(),
          partial_amounts
        },
        freshness,
        error_code: null
      }
      return route.fulfill({ json: data })
    }
    const products: FunnelProduct[] = noData
      ? []
      : Array.from(
          { length: isOzon ? (options.twoOzon ? 2 : 1) : 29 },
          (_, index) => {
            const number = isOzon ? 23 - index : index,
              code = String(101 + number),
              sku = isOzon ? `900${code}` : code
            return {
              ...figures(
                (index >= 24 ? index - 23 : number + 1) *
                  (isOzon ? 2 : 1) *
                  5 *
                  factor *
                  known,
                traffic
              ),
              nm_id: isOzon ? '' : code,
              marketplace_code: sku,
              id: `${isOzon ? 'oz' : 'wb'}-${sku}`,
              marketplace: isOzon ? 'ozon' : 'wildberries',
              identifier_kind: isOzon ? 'sku' : 'nm_id',
              title:
                number === 23
                  ? isOzon
                    ? 'Мотоботы Track'
                    : 'Мотошлем Trail'
                  : `Модель ${number}`,
              vendor_code: `${isOzon ? 'OZ' : 'WB'}-${code}`,
              photos:
                number === 23
                  ? [
                      'https://analytics-test.local/front.svg',
                      'https://analytics-test.local/back.svg'
                    ]
                  : [],
              barcodes: [`000${code}`],
              partial_amounts
            }
          }
        )
    const data: FunnelReport = {
      ...range,
      status: noData ? 'no_data' : known === days.length ? 'ready' : 'partial',
      period_days: days.length,
      known_days: known,
      currency,
      buyouts_by: 'order_date',
      buyouts_maturing_from: range.date_from,
      totals,
      daily: days.map((day, index) => ({
        day,
        ...(index < known ? figures(basis * factor, traffic) : unknown()),
        partial_amounts
      })),
      products,
      products_truncated: !!options.truncated,
      freshness,
      is_loading: state.partial && !past,
      error_code: null,
      available_metrics: Object.keys(figures(1)).filter(
        field =>
          traffic ||
          ![
            'opens',
            'carts',
            'add_to_cart_percent',
            'cart_to_order_percent',
            'open_to_order_percent'
          ].includes(field)
      ),
      partial_amounts
    }
    return route.fulfill({ json: data })
  })
  return state
}
