import { type Page, expect, test } from '@playwright/test'

import { ozon, wb } from './fixtures'
import { mockPlans } from './supply-plans-fixtures'

const output =
  'C:/Users/Artem/Documents/ChatGPT/PERK/outputs/web-supply-clusters-20261107'

async function mockDestinations(page: Page, role = 'owner') {
  const base = await mockPlans(page, role)
  const state = {
    base,
    requests: [] as URL[],
    writes: 0,
    loading: false,
    fail: false,
    csrf: true
  }
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url()),
      store = url.searchParams.get('store_id') ?? wb
    const destination = url.searchParams.get('destination_id')
    const prefix = '/inventory/replenishment'
    if (!url.pathname.includes(prefix)) return route.fallback()
    if (!url.pathname.includes('/destinations') && !destination)
      return route.fallback()
    state.requests.push(url)
    if (state.fail)
      return route.fulfill({
        status: 503,
        json: { detail: 'Ошибка детализации' }
      })
    if (url.pathname.endsWith('/refresh')) {
      state.writes++
      state.csrf &&= route.request().headers()['x-csrf-token'] === 'pc_test'
      state.loading = true
      return route.fulfill({ json: { queued: 2 } })
    }
    if (url.pathname.endsWith('/destinations')) {
      const rows = [
        {
          id: 'wb-region:center',
          name: 'Центр',
          store_id: wb,
          store_name: 'PERK Test WB',
          marketplace: 'wildberries'
        },
        {
          id: '11',
          name: 'Москва',
          store_id: ozon,
          store_name: 'PERK Test Ozon',
          marketplace: 'ozon'
        }
      ]
      const selected = url.searchParams.get('store_id')
      return route.fulfill({
        json: {
          items: rows
            .filter(r => !selected || r.store_id === selected)
            .map(r => ({
              ...r,
              recommended_units: 60,
              product_count: 1,
              urgent_count: 1,
              partial: state.loading,
              updated_at: '2026-11-07T10:00:00Z'
            })),
          loaded_products: 1,
          total_products: 3,
          failed_products: 0,
          loading: state.loading
        }
      })
    }
    if (url.pathname.endsWith('/export'))
      return route.fulfill({
        contentType: 'text/csv',
        body: 'Направление;Количество\n' + destination + ';60'
      })
    const quantity = Math.max(
      0,
      Number(url.searchParams.get('target_days') ?? 30) * 2 -
        Math.max(
          0,
          10 - Number(url.searchParams.get('lead_time_days') ?? 7) * 2
        )
    )
    const name = store === ozon ? 'Москва' : 'Центр'
    return route.fulfill({
      json: {
        target_days: Number(url.searchParams.get('target_days') ?? 30),
        lead_time_days: Number(url.searchParams.get('lead_time_days') ?? 7),
        destination_id: destination,
        destination_name: name,
        recommended_units: quantity,
        product_count: 1,
        urgent_count: 1,
        unknown_count: 0,
        no_orders_count: 0,
        partial: state.loading,
        loading: state.loading,
        stale: false,
        updated_at: '2026-11-07T10:00:00Z',
        items: [
          {
            id: 'product-0',
            marketplace: store === ozon ? 'ozon' : 'wildberries',
            marketplace_code: '101',
            demand_basis: store === ozon ? 'ozon_sales' : 'wb_orders',
            store_id: store,
            store_name: store === ozon ? 'PERK Test Ozon' : 'PERK Test WB',
            nm_id: store === ozon ? '' : '42',
            vendor_code: 'TEST-42',
            title: 'Шлем Trail',
            photo: null,
            colors: [],
            barcodes: ['001'],
            stock: 10,
            daily_orders: '2',
            days_of_stock: '5',
            quantity,
            required_quantity: quantity,
            box_multiple: 1,
            urgent: true,
            incoming_quantity: 5,
            incoming_reduction: 5,
            destination_id: destination,
            destination_name: name
          }
        ],
        count: 1,
        limit: 20,
        offset: 0
      }
    })
  })
  return state
}

test('directions load only when opened and a plan keeps the selected native destination', async ({
  page
}) => {
  const state = await mockDestinations(page)
  await page.goto('/supplies')
  await page.getByRole('combobox', { name: 'Выбрать кабинет' }).click()
  await page
    .getByRole('option', { name: 'PERK Test Ozon · Ozon', exact: true })
    .click()
  await expect(
    page.getByRole('tab', { name: 'Кластеры Ozon', exact: true })
  ).toBeVisible()
  expect(state.requests).toHaveLength(0)
  await page.getByRole('tab', { name: 'Кластеры Ozon', exact: true }).click()
  await page
    .getByRole('button', {
      name: 'Открыть направление Москва · PERK Test Ozon'
    })
    .click()
  await expect(
    page.getByRole('heading', { name: 'Москва', exact: true })
  ).toBeVisible()
  await expect(page.locator('.supply-data tbody tr')).toContainText(
    'Шлем Trail'
  )
  await page.getByRole('button', { name: 'Создать план', exact: true }).click()
  await expect(page.getByLabel('Склад / кластер', { exact: true })).toHaveValue(
    'Москва'
  )
  await expect(
    page.getByLabel('Склад / кластер', { exact: true })
  ).toHaveAttribute('readonly', '')
  await page
    .getByRole('dialog')
    .getByRole('button', { name: 'Создать план', exact: true })
    .click()
  expect(state.base.creates[0]?.data.destination_id).toBe('11')
  await expect(
    page.getByRole('dialog').getByLabel('Склад / кластер', { exact: true })
  ).toHaveAttribute('readonly', '')
})

test('cabinet filters keep native Ozon cluster ids and WB regions separate', async ({
  page
}) => {
  await mockDestinations(page)
  await page.goto('/supplies')
  await page.getByRole('combobox', { name: 'Выбрать кабинет' }).click()
  await page
    .getByRole('option', { name: 'PERK Test Ozon · Ozon', exact: true })
    .click()
  await page.getByRole('tab', { name: 'Кластеры Ozon', exact: true }).click()
  await page.getByRole('combobox', { name: 'Выбрать кабинет' }).click()
  await page.getByRole('option', { name: 'Все кабинеты', exact: true }).click()
  await expect(
    page
      .getByRole('region', { name: 'Направления поставок' })
      .getByRole('button')
  ).toHaveCount(1)
  await page
    .getByRole('button', {
      name: 'Открыть направление Москва · PERK Test Ozon'
    })
    .click()
  await expect(
    page.getByRole('heading', { name: 'Москва', exact: true })
  ).toBeVisible()
  await page
    .getByRole('button', { name: 'Все направления', exact: true })
    .click()
  await page.screenshot({ path: output + '/destinations.png', fullPage: true })
  await page
    .getByRole('combobox', { name: 'Кабинет в списке поставок' })
    .selectOption(wb)
  await expect(
    page.getByRole('button', {
      name: 'Открыть направление Москва · PERK Test Ozon'
    })
  ).toHaveCount(0)
})

test('planning parameters and export keep the chosen direction', async ({
  page
}) => {
  const state = await mockDestinations(page)
  await page.goto('/supplies')
  await page.getByRole('combobox', { name: 'Выбрать кабинет' }).click()
  await page
    .getByRole('option', { name: 'PERK Test Ozon · Ozon', exact: true })
    .click()
  await page.getByRole('tab', { name: 'Кластеры Ozon', exact: true }).click()
  await page
    .getByRole('button', {
      name: 'Открыть направление Москва · PERK Test Ozon'
    })
    .click()
  await page.getByLabel('Запас после поступления, дней').fill('60')
  await page.getByLabel('Доставка и приёмка, дней').fill('0')
  await page.getByRole('button', { name: 'Рассчитать', exact: true }).click()
  await expect(page.locator('.supply-data tbody tr')).toContainText('110 шт.')
  const download = page.waitForEvent('download')
  await page
    .getByRole('button', { name: 'Выгрузить потребность', exact: true })
    .click()
  await download
  const url = state.requests.find(r => r.pathname.endsWith('/export'))!
  expect(url.searchParams.get('destination_id')).toBe('11')
  expect(url.searchParams.get('store_id')).toBe(ozon)
  expect(url.searchParams.get('target_days')).toBe('60')
})

test('loading uses a protected explicit action and partial results remain visible', async ({
  page
}) => {
  const state = await mockDestinations(page)
  await page.goto('/supplies')
  await page.getByRole('combobox', { name: 'Выбрать кабинет' }).click()
  await page
    .getByRole('option', { name: 'PERK Test Ozon · Ozon', exact: true })
    .click()
  await page.getByRole('tab', { name: 'Кластеры Ozon', exact: true }).click()
  await page
    .getByRole('button', { name: 'Загрузить направления', exact: true })
    .click()
  await expect(page.getByRole('status')).toContainText(
    'Загружено товаров: 1 из 3'
  )
  expect(state.writes).toBe(1)
  expect(state.csrf).toBe(true)
  await expect(
    page.getByRole('button', {
      name: 'Открыть направление Москва · PERK Test Ozon'
    })
  ).toBeVisible()
})

test('narrow screen fits and read-only staff can inspect a cluster without editing plans', async ({
  page
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mockDestinations(page, 'viewer')
  await page.goto('/supplies')
  await page.getByRole('combobox', { name: 'Выбрать кабинет' }).click()
  await page
    .getByRole('option', { name: 'PERK Test Ozon · Ozon', exact: true })
    .click()
  await page.getByRole('tab', { name: 'Кластеры Ozon', exact: true }).click()
  await page
    .getByRole('button', {
      name: 'Открыть направление Москва · PERK Test Ozon'
    })
    .click()
  await expect(page.locator('.supply-data tbody tr')).toHaveCount(1)
  await expect(
    page.getByRole('button', { name: 'Создать план', exact: true })
  ).toHaveCount(0)
  const size = await page.evaluate(() => ({
    width: window.innerWidth,
    content: document.documentElement.scrollWidth
  }))
  expect(size.content).toBeLessThanOrEqual(size.width)
  await page.screenshot({
    path: output + '/destinations-mobile.png',
    fullPage: true
  })
})
