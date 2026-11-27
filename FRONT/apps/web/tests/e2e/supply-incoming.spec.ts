import { type Page, expect, test } from '@playwright/test'

import { ozon, wb } from './fixtures'
import { mockSupplies } from './supplies-fixtures'

const output =
  'C:/Users/Artem/Documents/ChatGPT/PERK/outputs/web-supply-incoming-20261106'

async function incoming(page: Page, known = true) {
  await mockSupplies(page)
  await page.route('**/inventory/replenishment?*', async route => {
    const url = new URL(route.request().url())
    const store = url.searchParams.get('store_id') ?? wb
    const isOzon = store === ozon
    const item = {
      id: 'product-42',
      marketplace: isOzon ? 'ozon' : 'wildberries',
      marketplace_code: '101',
      demand_basis: isOzon ? 'ozon_sales' : 'wb_orders',
      store_id: store,
      store_name: isOzon ? 'PERK Test Ozon' : 'PERK Test WB',
      nm_id: isOzon ? '' : '42',
      vendor_code: 'MODEL-42',
      title: 'Шлем Trail',
      photo: null,
      colors: ['чёрный'],
      barcodes: ['001'],
      stock: 100,
      daily_orders: '5',
      days_of_stock: '20',
      quantity: 36,
      required_quantity: 35,
      box_multiple: 6,
      urgent: false,
      incoming_quantity: known ? 50 : null,
      incoming_reduction: known ? 50 : 0
    }
    await route.fulfill({
      json: {
        target_days: 30,
        lead_time_days: 7,
        urgent_days: 7,
        recommended_units: 36,
        product_count: 1,
        urgent_count: 0,
        unknown_count: 0,
        no_orders_count: 0,
        partial: false,
        loading: false,
        stale: false,
        updated_at: '2026-11-06T12:00:00Z',
        incoming_units: known ? 50 : null,
        incoming_complete: known,
        items: url.searchParams.get('limit') === '0' ? [] : [item],
        count: 1,
        limit: 20,
        offset: 0
      }
    })
  })
}

test('native incoming quantities and the actual reduction are visible for WB and Ozon', async ({
  page
}) => {
  await incoming(page)
  await page.goto('/supplies')
  const row = page.locator('.supply-data tbody tr').first()
  await expect(
    page.getByRole('columnheader', { name: 'В поставках', exact: true })
  ).toBeVisible()
  await expect(row).toContainText('50 шт.')
  await expect(row).toContainText('36 шт.')
  await page
    .getByRole('button', { name: 'Рекомендация Шлем Trail · MODEL-42' })
    .click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toContainText('В оформленных поставках')
  await expect(dialog).toContainText('Снижение потребности')
  await expect(dialog).toContainText('50 шт.')
  await page.keyboard.press('Escape')
  await page
    .getByRole('button', { name: 'О расчёте потребности', exact: true })
    .hover()
  await expect(page.getByRole('tooltip')).toContainText('плановая дата плюс')
  await page.keyboard.press('Escape')
  await page.mouse.move(1200, 900)
  await expect(page.getByRole('tooltip')).toHaveCount(0)
  await page.screenshot({ path: output + '/incoming.png', fullPage: true })
  await page.getByRole('combobox', { name: 'Выбрать кабинет' }).click()
  await page
    .getByRole('option', { name: 'PERK Test Ozon · Ozon', exact: true })
    .click()
  await page
    .getByRole('button', { name: 'Рекомендация Шлем Trail · MODEL-42' })
    .click()
  await expect(page.getByRole('dialog')).toContainText('PERK Test Ozon')
  await expect(page.getByRole('dialog')).toContainText('50 шт.')
})

test('unavailable contents render a dash and do not pretend to reduce the recommendation', async ({
  page
}) => {
  await incoming(page, false)
  await page.goto('/supplies')
  const row = page.locator('.supply-data tbody tr').first()
  await expect(row.locator('td').nth(3)).toHaveText('—')
  await page
    .getByRole('button', { name: 'Рекомендация Шлем Trail · MODEL-42' })
    .click()
  await expect(page.getByRole('dialog')).not.toContainText(
    'Снижение потребности'
  )
})

test('incoming column stays inside the scrollable table on a phone viewport', async ({
  page
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await incoming(page)
  await page.goto('/supplies')
  await expect(page.locator('.supply-data tbody tr')).toHaveCount(1)
  const sizes = await page.evaluate(() => ({
    width: window.innerWidth,
    content: document.documentElement.scrollWidth
  }))
  expect(sizes.content).toBeLessThanOrEqual(sizes.width)
  await page.screenshot({
    path: output + '/incoming-mobile.png',
    fullPage: true
  })
})
