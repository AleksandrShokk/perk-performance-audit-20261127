import { lastDays } from '@app/analytics/dates'
import type { Page } from '@playwright/test'
import { Decimal } from 'decimal.js'

import type { ExpenseView, FinanceOverview, TaxSettingView } from '@app/api'

import { mockApi, ozon, wb, wid } from './fixtures'

export async function mockFinance(
  page: Page,
  options: {
    profit?: boolean
    failFirstExpense?: boolean
    holdExpense?: Promise<void>
    partial?: boolean
    empty?: boolean
  } = {}
) {
  await mockApi(page)
  const date = lastDays(1).date_to
  const state = {
    reportCalls: 0,
    paths: [] as string[],
    requestIds: [] as string[],
    expenseStores: [] as string[],
    taxWrites: [] as Record<string, unknown>[],
    templates: [] as string[],
    previews: [] as string[],
    applied: [] as string[],
    csrf: true,
    multipart: false,
    csv: '',
    expenses: [] as ExpenseView[],
    deleted: [] as string[]
  }
  let settings: TaxSettingView[] = [
    {
      effective_from: '2025-01-01',
      regime: 'usn_income',
      rate: '6',
      vat_rate: '0',
      income_base: 'revenue'
    }
  ]
  const group = (
    key: string,
    title: string,
    amount: string | null,
    share: string | null,
    lines = [{ key, title, amount, unit: 'money' as const }]
  ) => ({ key, title, amount, share_percent: share, lines })
  await page.route('**/api/v1/**', async route => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    const body = request.headers()['content-type']?.includes('application/json')
      ? request.postDataJSON()
      : null
    const json = (data: unknown, status = 200) =>
      route.fulfill({
        status,
        contentType: 'application/json',
        body: JSON.stringify(data)
      })
    if (options.profit === false && path.endsWith('/workspaces'))
      return json([
        {
          id: wid,
          name: 'PERK Test',
          role: 'manager',
          permissions: ['finance.read', 'reports.export'],
          store_ids: null
        }
      ])
    if (path.endsWith('/finance/overview')) {
      state.reportCalls++
      state.paths.push(request.url())
      const store = url.searchParams.get('store_id')
      const multiplier = store === wb ? 1 : store === ozon ? 2 : 3
      const extra = state.expenses.reduce(
        (sum, item) => sum.plus(item.amount),
        new Decimal(0)
      )
      const money = (amount: string) =>
        new Decimal(amount).times(multiplier).toFixed(2)
      const report: FinanceOverview = {
        date_from: url.searchParams.get('date_from')!,
        date_to: url.searchParams.get('date_to')!,
        currency: 'RUB',
        updated_at: new Date().toISOString(),
        is_partial: !!options.partial && state.reportCalls < 2,
        is_loading: !!options.partial && state.reportCalls < 2,
        period_covered: !options.partial || state.reportCalls >= 2,
        expenses_exclude_cogs: false,
        total_stores: store ? 1 : 2,
        totals: {
          seller_revenue: money('1284600.27'),
          marketplace_revenue: money('1200000.00'),
          expenses_before_tax: new Decimal(money('433500.17'))
            .plus(extra)
            .toFixed(2),
          profit_before_tax: money('851100.10'),
          settlement: money('982400.55')
        },
        groups: [
          {
            ...group('sales', 'Продажи и возвраты', money('1284600.27'), '100'),
            lines: [
              {
                key: 'sales',
                title: 'Продажи по цене продавца',
                amount: money('1400000.00'),
                unit: 'money'
              },
              {
                key: 'returns',
                title: 'Возвраты по цене продавца',
                amount: money('-115399.73'),
                unit: 'money'
              },
              {
                key: 'units',
                title: 'Продано за вычетом возвратов',
                amount: '342',
                unit: 'units'
              }
            ]
          },
          group('fees', 'Комиссия и эквайринг', money('150000.17'), '11.7'),
          group('logistics', 'Логистика', money('85000'), '6.6'),
          group('warehouse', 'Хранение и приёмка', money('15800'), '1.2'),
          group('advertising', 'Реклама', money('27500'), '2.1'),
          group('services', 'Сервисы маркетплейса', money('1200'), '0.1'),
          group('penalties', 'Штрафы', money('4000'), '0.3'),
          group('compensations', 'Компенсации', money('2500'), '0.2'),
          group('cogs', 'Себестоимость', money('150000'), '11.7'),
          group('external', 'Внешние расходы', extra.toFixed(2), '0')
        ],
        taxes: {
          configured_stores: 1,
          total_stores: store ? 1 : 2,
          vat: '0.00',
          tax: money('77076.02'),
          net_profit: money('774024.08'),
          notes: []
        },
        notes: []
      }
      if (options.empty) {
        report.totals = {
          seller_revenue: null,
          marketplace_revenue: null,
          expenses_before_tax: null,
          profit_before_tax: null,
          settlement: null
        }
        report.groups = report.groups.map(group => ({
          ...group,
          amount: null,
          share_percent: null,
          lines: group.lines.map(line => ({ ...line, amount: null }))
        }))
        report.taxes = {
          ...report.taxes,
          configured_stores: 0,
          vat: null,
          tax: null,
          net_profit: null
        }
      }
      return json(report)
    }
    const handled =
      /\/(expenses|tax-settings|cost-imports|costs\/template)(\/|$)/.test(path)
    if (!handled) return route.fallback()
    if (request.method() !== 'GET')
      state.csrf &&= request.headers()['x-csrf-token'] === 'pc_test'
    if (path.endsWith('/expenses') && request.method() === 'POST') {
      state.requestIds.push(body.request_id)
      state.expenseStores.push(path)
      if (options.holdExpense) await options.holdExpense
      if (options.failFirstExpense && state.requestIds.length === 1)
        return json({ detail: 'Временная ошибка. Повторите сохранение.' }, 503)
      const existing = state.expenses.find(item => item.id === body.request_id)
      if (existing) return json(existing, 201)
      const row: ExpenseView = {
        ...body,
        id: body.request_id,
        created_at: new Date().toISOString()
      }
      state.expenses.push(row)
      return json(row, 201)
    }
    if (path.endsWith('/expenses') && request.method() === 'GET')
      return json(
        state.expenses.slice(
          Number(url.searchParams.get('offset') ?? 0),
          Number(url.searchParams.get('offset') ?? 0) + 50
        )
      )
    if (path.includes('/expenses/') && request.method() === 'DELETE') {
      const id = path.split('/').at(-1)!
      state.deleted.push(id)
      state.expenses = state.expenses.filter(item => item.id !== id)
      return route.fulfill({ status: 204 })
    }
    if (path.endsWith('/tax-settings')) {
      if (request.method() === 'PUT') {
        state.taxWrites.push(body)
        settings = [body]
        return json(body)
      }
      return json(settings)
    }
    if (path.endsWith('/costs/template')) {
      state.templates.push(path)
      return route.fulfill({
        status: 200,
        contentType:
          'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        body: Buffer.from('synthetic workbook test only')
      })
    }
    if (path.endsWith('/cost-imports')) {
      state.multipart =
        request
          .headers()
          ['content-type']?.includes('multipart/form-data; boundary=') ?? false
      state.previews.push(path)
      const invalid = request
        .postDataBuffer()
        ?.toString()
        .includes('invalid.xlsx')
      return json({
        preview_id: invalid ? null : '50000000-0000-4000-8000-000000000001',
        rows_count: 2,
        valid_count: invalid ? 0 : 2,
        error_count: invalid ? 2 : 0,
        errors: invalid
          ? [{ row: 2, message: 'Не найдена себестоимость' }]
          : [],
        items: invalid
          ? []
          : [
              {
                variant_id: 'variant-test',
                marketplace_code: 'OZ-001',
                product_title: 'Мотошлем Trail',
                row: 2,
                amount: '1250.1234',
                currency: 'RUB',
                effective_from: date,
                action: 'insert'
              }
            ],
        can_apply: !invalid
      })
    }
    if (path.endsWith('/apply')) {
      state.applied.push(path)
      return json({
        preview_id: '50000000-0000-4000-8000-000000000001',
        inserted: 2,
        unchanged: 0
      })
    }
    return route.fallback()
  })
  return state
}
