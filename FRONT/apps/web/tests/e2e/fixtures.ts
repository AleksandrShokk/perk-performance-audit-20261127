import { HISTORY_START, eachDay, lastDays } from '@app/analytics/dates'
import { previousPeriod } from '@app/analytics/sales'
import type { Page } from '@playwright/test'

export const wid = '10000000-0000-4000-8000-000000000001'
export const wb = '20000000-0000-4000-8000-000000000001'
export const ozon = '20000000-0000-4000-8000-000000000002'
const date = lastDays(1).date_to
const features = [
  'catalog',
  'analytics',
  'finance',
  'finance_details',
  'inventory',
  'supplies',
  'supply_history'
]
const user = {
  id: '30000000-0000-4000-8000-000000000001',
  email: 'web-test@perk.local',
  email_verified: true,
  phone: '+7 *** ***-00-01',
  phone_channel: 'telegram',
  totp_enabled: false,
  strong_factor_enabled: true,
  session_mfa_verified: true,
  step_up_valid: true,
  strong_step_up_valid: true,
  mfa_enabled: true
}
const challenge = {
  challenge_id: '40000000-0000-4000-8000-000000000001',
  channel: 'telegram',
  destination: '+7 *** ***-00-01',
  expires_in: 300,
  resend_after: 60
}
function figures(days: number, multiplier: number) {
  return {
    opens: 100 * days * multiplier,
    carts: 20 * days * multiplier,
    orders: 5 * days * multiplier,
    buyouts: 4 * days * multiplier,
    cancellations: days * multiplier,
    wishlist: 0,
    orders_amount: String(5000 * days * multiplier),
    buyouts_amount: String(4000 * days * multiplier),
    cancellations_amount: String(1000 * days * multiplier),
    add_to_cart_percent: '20',
    cart_to_order_percent: '25',
    open_to_order_percent: '5',
    buyout_percent: '80'
  }
}
function inventory(multiplier: number, offset: number, limit: number) {
  const amounts = (units: number) => ({
    units: units * multiplier,
    retail_value: String(units * multiplier * 1000),
    retail_complete: true,
    cost_value: String(units * multiplier * 400),
    cost_complete: true,
    updated_at: new Date().toISOString()
  })
  return {
    fbo: amounts(1200),
    fbs: amounts(400),
    total: amounts(1600),
    turnover_days: '23.5',
    turnover_supported: true,
    turnover_basis: 'wb_orders_28d',
    count: 1,
    limit,
    offset,
    currency: 'RUB',
    can_cost: true,
    is_loading: false,
    missing_sources: [],
    items: offset
      ? []
      : [
          {
            product: {
              id: 'synthetic-product-1',
              store_id: wb,
              store_name: 'PERK Test WB',
              nm_id: '101',
              vendor_code: 'HELMET-01',
              title: 'Мотошлем Trail',
              brand: 'PERK Test',
              subject: 'Шлемы',
              colors: ['чёрный'],
              photos: [],
              variants: [],
              stock: 1600,
              stock_updated_at: new Date().toISOString(),
              stock_stale: false,
              missing_cost_variants: 0
            },
            fbo: amounts(1200),
            fbs: amounts(400),
            turnover_days: '23.5',
            turnover_status: 'ready'
          }
        ]
  }
}
export async function mockApi(
  page: Page,
  {
    signedIn = true,
    mfa = true,
    financeForbidden = false,
    role = 'owner'
  }: {
    signedIn?: boolean
    mfa?: boolean
    financeForbidden?: boolean
    role?: string
  } = {}
) {
  const state = {
    signedIn,
    mfa,
    phoneBound: true,
    loginCalls: 0,
    verifyCalls: 0,
    logoutCalls: 0,
    reportCalls: 0,
    csrfValid: true
  }
  if (signedIn)
    await page.context().addCookies([
      {
        name: 'perk_csrf',
        value: 'pc_test',
        url: 'http://localhost:3000',
        sameSite: 'Strict'
      }
    ])
  await page.route('**/api/v1/**', async route => {
    const req = route.request()
    const url = new URL(req.url())
    const path = url.pathname
    const body = req.headers()['content-type']?.includes('application/json')
      ? (req.postDataJSON() as Record<string, unknown> | null)
      : null
    const fulfill = (
      data: unknown,
      status = 200,
      headers: Record<string, string> = {}
    ) =>
      route.fulfill({
        status,
        contentType: 'application/json',
        body: JSON.stringify(data),
        headers
      })
    if (
      req.method() === 'POST' &&
      !path.endsWith('/login') &&
      !path.includes('/password/') &&
      !path.includes('/register')
    )
      state.csrfValid &&= req.headers()['x-csrf-token'] === 'pc_test'
    if (path.endsWith('/insights/funnel/availability'))
      return fulfill({ date_from: HISTORY_START, date_to: lastDays(1).date_to })
    if (path.endsWith('/auth/login')) {
      state.loginCalls++
      state.signedIn = true
      state.mfa = false
      return fulfill(
        {
          expires_in: 900,
          csrf_token: 'pc_test',
          mfa_required: true,
          second_factor: { challenge, available: ['telegram', 'recovery'] }
        },
        200,
        { 'set-cookie': 'perk_csrf=pc_test; Path=/; SameSite=Strict' }
      )
    }
    if (path.endsWith('/auth/register/verify')) {
      state.signedIn = true
      state.mfa = true
      state.phoneBound = false
      return fulfill(
        { expires_in: 900, csrf_token: 'pc_test', mfa_required: false },
        201,
        { 'set-cookie': 'perk_csrf=pc_test; Path=/; SameSite=Strict' }
      )
    }
    if (path.endsWith('/auth/phone')) return fulfill(challenge)
    if (path.endsWith('/auth/phone/confirm')) {
      state.phoneBound = true
      return fulfill({
        recovery_codes: [
          'rc_SYNTHETIC_TEST_ONLY_111',
          'rc_SYNTHETIC_TEST_ONLY_222'
        ]
      })
    }
    if (path.endsWith('/auth/me'))
      return state.signedIn
        ? fulfill({
            ...user,
            session_mfa_verified: state.mfa,
            strong_factor_enabled: state.phoneBound
          })
        : fulfill({ detail: 'Authentication required' }, 401)
    if (path.endsWith('/auth/mfa/verify')) {
      state.verifyCalls++
      if (body?.code !== '123456')
        return fulfill(
          { detail: { code: 'otp_invalid', message: 'Неверный код' } },
          400
        )
      state.mfa = true
      return fulfill({
        expires_in: 900,
        csrf_token: 'pc_test',
        mfa_required: false
      })
    }
    if (
      path.endsWith('/auth/mfa/send') ||
      path.endsWith('/auth/password/forgot') ||
      path.endsWith('/auth/register') ||
      path.endsWith('/auth/register/resend')
    )
      return fulfill(
        {
          ...challenge,
          channel: path.includes('/mfa/') ? 'telegram' : 'email'
        },
        202
      )
    if (path.endsWith('/auth/password/reset'))
      return fulfill({ message: 'Пароль изменён' })
    if (path.endsWith('/auth/logout')) {
      state.logoutCalls++
      state.signedIn = false
      return fulfill({ ok: true }, 200, {
        'set-cookie': 'perk_csrf=; Path=/; Max-Age=0'
      })
    }
    if (path === '/api/v1/workspaces')
      return fulfill([
        {
          id: wid,
          name: 'PERK Test',
          role,
          permissions: role === 'viewer' ? ['inventory.read'] : [],
          store_ids: null
        }
      ])
    if (path.endsWith('/stores'))
      return fulfill([
        {
          id: wb,
          name: 'PERK Test WB',
          marketplace: 'wildberries',
          connection_status: 'connected',
          last_checked_at: null,
          reports_available: true,
          features
        },
        {
          id: ozon,
          name: 'PERK Test Ozon',
          marketplace: 'ozon',
          connection_status: 'connected',
          last_checked_at: null,
          reports_available: false,
          features
        }
      ])
    if (path.includes('/insights/funnel')) {
      state.reportCalls++
      const start = url.searchParams.get('date_from') ?? date
      const end = url.searchParams.get('date_to') ?? date
      const range = { date_from: start, date_to: end }
      const days = eachDay(range)
      const m = path.includes(ozon) ? 2 : 1
      const totals = figures(days.length, m)
      const freshness = { computed_at: new Date().toISOString(), stale: false }
      if (path.endsWith('/summary'))
        return fulfill({
          ...range,
          totals,
          data_source: 'ozon_postings',
          status: 'ready',
          currency: 'RUB',
          previous: { ...previousPeriod(range), totals },
          error_code: null,
          freshness,
          partial_amounts: []
        })
      return fulfill({
        ...range,
        status: 'ready',
        period_days: days.length,
        known_days: days.length,
        currency: 'RUB',
        buyouts_by: 'order_date',
        buyouts_maturing_from: start,
        totals,
        daily: days.map(day => ({
          day,
          ...figures(1, m),
          partial_amounts: []
        })),
        products: [
          {
            ...totals,
            nm_id: '101',
            marketplace_code: '101',
            partial_amounts: []
          }
        ],
        products_truncated: false,
        freshness,
        is_loading: false,
        available_metrics: Object.keys(totals),
        partial_amounts: []
      })
    }
    const store = url.searchParams.get('store_id')
    const m = store === wb ? 1 : store === ozon ? 2 : 3
    if (path.endsWith('/finance/overview')) {
      if (financeForbidden) return fulfill({ detail: 'Forbidden' }, 403)
      const group = (key: string, title: string, value: number) => ({
        key,
        title,
        amount: String(value * m),
        share_percent: null,
        lines: [
          {
            key: key === 'warehouse' ? 'storage' : key,
            title,
            amount: String(value * m),
            unit: 'money'
          }
        ]
      })
      return fulfill({
        date_from: url.searchParams.get('date_from'),
        date_to: date,
        currency: 'RUB',
        updated_at: new Date().toISOString(),
        is_partial: false,
        is_loading: false,
        period_covered: true,
        expenses_exclude_cogs: false,
        total_stores: store ? 1 : 2,
        totals: {
          seller_revenue: String(100000 * m),
          marketplace_revenue: String(100000 * m),
          expenses_before_tax: String(40000 * m),
          profit_before_tax: String(60000 * m),
          settlement: String(80000 * m)
        },
        groups: [
          group('sales', 'Продажи и возвраты', 100000),
          group('fees', 'Комиссия и эквайринг', 8000),
          group('logistics', 'Логистика', 10000),
          group('warehouse', 'Хранение', 2000),
          group('cogs', 'Себестоимость', 20000)
        ],
        taxes: {
          configured_stores: store ? 1 : 2,
          total_stores: store ? 1 : 2,
          vat: '0',
          tax: String(6000 * m),
          net_profit: String(54000 * m),
          notes: []
        },
        notes: []
      })
    }
    if (path.endsWith('/product-models'))
      return fulfill({
        items: inventory(m, 0, 20).items.map(row => ({
          id: 'synthetic-card-1',
          store_id: row.product.store_id,
          store_name: row.product.store_name,
          marketplace: store === ozon ? 'ozon' : 'wildberries',
          title: row.product.title,
          brand: row.product.brand,
          grouping: 'marketplace',
          products: [row.product],
          stock: row.product.stock,
          missing_cost_variants: 0
        })),
        total: 1,
        total_products: 1,
        total_variants: 0,
        currency: 'RUB',
        limit: 20,
        offset: 0,
        is_loading: false,
        is_partial: false
      })
    if (path.endsWith('/products'))
      return fulfill({
        items: inventory(m, 0, 10).items.map(row => row.product),
        count: 1,
        limit: 100,
        offset: 0
      })
    if (path.endsWith('/inventory/overview'))
      return fulfill(
        inventory(
          m,
          Number(url.searchParams.get('offset') ?? 0),
          Number(url.searchParams.get('limit') ?? 3)
        )
      )
    if (path.endsWith('/inventory/replenishment'))
      return fulfill({
        recommended_units: 150 * m,
        product_count: 12 * m,
        urgent_count: 3 * m,
        unknown_count: 0,
        no_orders_count: 0,
        partial: false,
        loading: false,
        stale: false,
        updated_at: new Date().toISOString(),
        items: [
          {
            id: 'test-product',
            store_id: store ?? wb,
            store_name: 'PERK Test',
            nm_id: '101',
            vendor_code: 'HELMET-01',
            title: 'Мотошлем Trail',
            photo: null,
            colors: [],
            barcodes: [],
            stock: 10,
            daily_orders: '2',
            days_of_stock: '5',
            quantity: 150 * m,
            urgent: true
          }
        ],
        count: 1,
        limit: 30,
        offset: 0,
        target_days: 30,
        lead_time_days: 7
      })
    if (path.endsWith('/inventory/supplies'))
      return fulfill({
        items: [
          {
            external_id: 'test-supply',
            store_id: store ?? wb,
            store_name: 'PERK Test',
            marketplace: store === ozon ? 'ozon' : 'wildberries',
            display_number: 'SUP-101',
            supply_id: '101',
            preorder_id: '201',
            status: 'ready_to_ship',
            planned_date: date,
            actual_date: null,
            created_date: date,
            destination: 'Тестовый склад',
            quantity: 150 * m,
            accepted_quantity: null
          }
        ],
        count: 1,
        limit: 30,
        offset: 0,
        loading: false,
        incomplete: false,
        missing_access: false,
        updated_at: new Date().toISOString(),
        stale: false
      })
    return fulfill({ detail: `Unmocked test route: ${path}` }, 404)
  })
  return state
}
