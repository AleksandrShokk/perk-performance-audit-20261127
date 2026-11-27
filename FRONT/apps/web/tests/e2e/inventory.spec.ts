import { type Page, expect, test } from '@playwright/test'

import { ozon } from './fixtures'
import { mockInventory } from './inventory-fixtures'

const output =
  'C:/Users/Artem/Documents/ChatGPT/PERK/outputs/web-inventory-20261106'
async function selectStore(page: Page, name: string) {
  await page.getByRole('combobox', { name: 'Выбрать кабинет' }).click()
  await page.getByRole('option', { name, exact: true }).click()
}
const openHelmet = (page: Page) =>
  page
    .getByRole('button', {
      name: 'Остатки Мотошлем Trail · WB-101',
      exact: true
    })
    .click()

test('inventory keeps unfiltered server totals while searching and paging the product table', async ({
  page
}) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  const state = await mockInventory(page)
  await page.goto('/inventory')
  const summary = page.getByRole('region', { name: 'Сводка остатков' })
  await expect(summary).toContainText('100 500,25 ₽')
  await expect(summary).toContainText('23,5')
  await expect(page.locator('.stock-data tbody tr')).toHaveCount(20)
  await expect(page.locator('.stock-data')).toContainText(
    'Нет заказов за 28 дней'
  )
  await page.screenshot({
    path: `${output}/inventory-light.png`,
    fullPage: true
  })
  await page
    .getByRole('button', { name: 'Следующая страница остатков' })
    .click()
  await expect(page.locator('.stock-data tbody tr')).toHaveCount(2)
  await page.getByRole('textbox', { name: 'Поиск остатков' }).fill('Модель 20')
  await expect(page.locator('.stock-data tbody tr')).toHaveCount(1)
  await expect(summary).toContainText('100 500,25 ₽')
  expect(
    state.requests.some(
      url =>
        url.searchParams.get('q') === 'Модель 20' &&
        url.searchParams.get('offset') === '0'
    )
  ).toBe(true)
  expect(
    state.requests
      .filter(url => url.searchParams.get('limit') === '0')
      .every(
        url => !url.searchParams.has('q') && !url.searchParams.has('in_stock')
      )
  ).toBe(true)
  await page.getByRole('button', { name: 'Очистить поиск' }).click()
  await page
    .getByRole('combobox', { name: 'Оценка остатков' })
    .selectOption('cost')
  await expect(page.locator('.stock-data tbody tr').first()).toContainText(
    '2 800,00 ₽'
  )
  await page
    .getByRole('combobox', { name: 'Отображение артикула' })
    .selectOption('barcode')
  await expect(page.locator('.stock-data tbody tr').first()).toContainText(
    '000101'
  )
  await page.getByRole('button', { name: 'Профиль и настройки' }).click()
  await page.getByRole('menuitemradio', { name: 'Тёмная', exact: true }).click()
  await page.screenshot({
    path: `${output}/inventory-dark.png`,
    fullPage: true
  })
  expect(errors).toEqual([])
})

test('product details show separate FBO/FBS sizes, warehouses, photos and copyable barcodes', async ({
  page,
  context
}) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  await mockInventory(page)
  await page.goto('/inventory')
  await openHelmet(page)
  const dialog = page.getByRole('dialog')
  await expect(dialog.locator('.gallery-position')).toHaveText('1 / 2')
  await dialog.getByRole('button', { name: 'Следующее фото' }).click()
  await expect(dialog.locator('.gallery-position')).toHaveText('2 / 2')
  await expect(dialog.getByRole('tabpanel')).toContainText('4 шт.')
  await expect(dialog.getByRole('tabpanel')).toContainText('2 шт.')
  await dialog
    .getByRole('button', { name: 'Скопировать штрихкод 000101', exact: true })
    .click()
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(
    '000101'
  )
  await dialog.getByRole('tab', { name: 'Склады площадки' }).click()
  await expect(dialog.getByRole('tabpanel')).toContainText('Коледино')
  await expect(dialog.getByRole('tabpanel')).not.toContainText('Склад Восток')
  await dialog.getByRole('tab', { name: 'Склады продавца' }).click()
  await expect(dialog.getByRole('tabpanel')).toContainText('Склад Восток')
  await dialog.getByRole('tab', { name: 'Склады площадки' }).click()
  await dialog
    .getByRole('combobox', { name: 'Размер в детализации' })
    .selectOption('uuid-1012')
  await expect(dialog.getByRole('tabpanel')).toContainText('Казань')
  await expect(dialog.getByRole('tabpanel')).not.toContainText('Коледино')
  await page.screenshot({
    path: `${output}/inventory-details.png`,
    fullPage: true
  })
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await page.getByRole('button', { name: 'Обновить остатки' }).click()
  await expect(
    page.getByRole('button', { name: 'Обновить остатки' })
  ).toBeEnabled()
})

test('Ozon preserves its native cover basis without invented warehouse breakdown', async ({
  page
}) => {
  const state = await mockInventory(page)
  await page.goto('/inventory')
  await selectStore(page, 'PERK Test Ozon · Ozon')
  await expect(
    page.getByRole('region', { name: 'Сводка остатков' })
  ).toContainText('18,2')
  await expect(page.locator('.stock-data')).toContainText('Запас в днях')
  await expect(page.locator('.stock-data')).toContainText(
    'Нет продаж за 28 дней'
  )
  await page
    .getByRole('button', { name: 'Остатки Мотоботы Track · OZ-900101' })
    .click()
  await page
    .getByRole('dialog')
    .getByRole('tab', { name: 'Склады площадки' })
    .click()
  await expect(page.getByText('Нет разбивки по складам')).toBeVisible()
  expect(
    state.requests.some(url => url.searchParams.get('store_id') === ozon)
  ).toBe(true)
})

test('mixed cabinet summaries remain server-native and FBS aggregation is configured explicitly', async ({
  page
}) => {
  const state = await mockInventory(page, { mode: 'unknown' })
  await page.goto('/inventory')
  await selectStore(page, 'Все кабинеты')
  const summary = page.getByRole('region', { name: 'Сводка остатков' })
  await expect(summary.locator('.stock-channel').nth(1)).toContainText('—')
  await summary.getByRole('button', { name: 'По кабинетам' }).click()
  await expect(
    page.getByRole('region', { name: 'Остатки по кабинетам' })
  ).toContainText('23,5')
  await expect(
    page.getByRole('region', { name: 'Остатки по кабинетам' })
  ).toContainText('18,2')
  await page.getByRole('button', { name: 'Учёт FBS', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('radio', { name: 'Разные склады' }).check()
  await dialog.getByRole('button', { name: 'Сохранить', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  expect(state.writes).toEqual([{ mode: 'separate', csrf: 'pc_test' }])
  await expect(summary.locator('.stock-channel').nth(1)).toContainText('50 шт.')
  await page.screenshot({
    path: `${output}/inventory-cabinets.png`,
    fullPage: true
  })
  await page
    .locator('.stock-store-button')
    .filter({ hasText: 'PERK Test Ozon' })
    .click()
  await expect(summary).toContainText('18,2')
})

test('closing a pending FBS save does not freeze the page or dismiss a new dialog', async ({
  page
}) => {
  const state = await mockInventory(page)
  await page.goto('/inventory')
  await selectStore(page, 'Все кабинеты')
  state.delaySave = true
  await page.getByRole('button', { name: 'Учёт FBS', exact: true }).click()
  await page.getByRole('radio', { name: 'Общий склад' }).check()
  await page.getByRole('button', { name: 'Сохранить', exact: true }).click()
  await expect.poll(() => state.writes.length).toBe(1)
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: 'Учёт FBS', exact: true }).click()
  await expect.poll(() => state.mode).toBe('shared')
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.keyboard.press('Escape')
  await page.getByRole('textbox', { name: 'Поиск остатков' }).fill('Trail')
  await expect(page.locator('.stock-data tbody tr')).toHaveCount(1)
})

test('stock-only permissions and server cost restrictions hide every cost control', async ({
  page
}) => {
  const state = await mockInventory(page, { role: 'viewer' })
  await page.goto('/inventory')
  await expect(page.locator('.stock-data')).toBeVisible()
  await expect(
    page.getByRole('combobox', { name: 'Оценка остатков' })
  ).toHaveCount(0)
  await expect(page.getByText('По себестоимости', { exact: true })).toHaveCount(
    0
  )
  await openHelmet(page)
  await expect(
    page.getByRole('dialog').getByText('По себестоимости', { exact: true })
  ).toHaveCount(0)
  await page.keyboard.press('Escape')
  await selectStore(page, 'Все кабинеты')
  await expect(
    page.getByRole('button', { name: 'Учёт FBS', exact: true })
  ).toHaveCount(0)
  state.canCost = false
  await page.reload()
  await expect(
    page.getByRole('combobox', { name: 'Оценка остатков' })
  ).toHaveCount(0)
})

test('empty and failed requests show useful states without a permanent loader', async ({
  page
}) => {
  const state = await mockInventory(page, { empty: true })
  await page.goto('/inventory')
  await expect(
    page.getByText('Нет товаров в наличии', { exact: true })
  ).toBeVisible()
  await page.getByRole('button', { name: 'Показать все товары' }).click()
  await expect(
    page.getByText('Товаров пока нет', { exact: true })
  ).toBeVisible()
  state.error = true
  await page.getByRole('button', { name: 'Обновить остатки' }).click()
  await expect(page.getByRole('alert').first()).toBeVisible({ timeout: 20000 })
})

test('inventory remains readable in a narrow browser window', async ({
  page
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mockInventory(page)
  await page.goto('/inventory')
  await expect(page.locator('.stock-data')).toBeVisible()
  const width = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    viewport: window.innerWidth
  }))
  expect(width.scroll).toBeLessThanOrEqual(width.viewport + 1)
  await page.screenshot({
    path: `${output}/inventory-narrow.png`,
    fullPage: true
  })
  await openHelmet(page)
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
})

test('server cost restrictions apply even to an owner', async ({ page }) => {
  await mockInventory(page, { canCost: false })
  await page.goto('/inventory')
  await expect(page.locator('.stock-data')).toBeVisible()
  await expect(
    page.getByRole('combobox', { name: 'Оценка остатков' })
  ).toHaveCount(0)
  await expect(page.getByText('По себестоимости', { exact: true })).toHaveCount(
    0
  )
  await openHelmet(page)
  await expect(
    page.getByRole('dialog').getByText('По себестоимости', { exact: true })
  ).toHaveCount(0)
})

test('a role without inventory access sends no stock requests', async ({
  page
}) => {
  const state = await mockInventory(page, { role: 'accountant' })
  await page.goto('/inventory')
  await expect(
    page.getByText('Нет доступа к остаткам', { exact: true })
  ).toBeVisible()
  expect(state.requests).toHaveLength(0)
  await expect(
    page
      .getByRole('navigation', { name: 'Разделы' })
      .getByRole('link', { name: 'Остатки', exact: true })
  ).toHaveCount(0)
})

test('background loading refreshes data without remounting open product details', async ({
  page
}) => {
  const state = await mockInventory(page, { loading: true })
  await page.goto('/inventory')
  await openHelmet(page)
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('tab', { name: 'Склады площадки' }).click()
  await dialog
    .getByRole('combobox', { name: 'Размер в детализации' })
    .selectOption('uuid-1012')
  const requests = state.requests.length
  await expect
    .poll(() => state.requests.length, { timeout: 15000 })
    .toBeGreaterThan(requests)
  await expect(dialog).toBeVisible()
  await expect(
    dialog.getByRole('combobox', { name: 'Размер в детализации' })
  ).toHaveValue('uuid-1012')
  await expect(
    dialog.getByRole('tab', { name: 'Склады площадки' })
  ).toHaveAttribute('aria-selected', 'true')
  state.loading = false
  await page.keyboard.press('Escape')
})
