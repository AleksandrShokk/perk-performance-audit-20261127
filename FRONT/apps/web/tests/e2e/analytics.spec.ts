import { type Page, expect, test } from '@playwright/test'

import { mockAnalytics } from './analytics-fixtures'
import { ozon, wb } from './fixtures'

const output =
  'C:/Users/Artem/Documents/ChatGPT/PERK/outputs/web-analytics-20261106'
async function selectStore(page: Page, name: string) {
  await page.getByRole('combobox', { name: 'Выбрать кабинет' }).click()
  await page.getByRole('option', { name, exact: true }).click()
}
const openHelmet = (page: Page) =>
  page
    .getByRole('button', {
      name: 'Аналитика Мотошлем Trail · WB-124',
      exact: true
    })
    .click()

test('analytics shows real totals, conversions, a reusable chart and working table views', async ({
  page
}) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await mockAnalytics(page)
  await page.goto('/analytics')
  await expect(
    page.getByRole('region', { name: 'Воронка продаж' })
  ).toContainText('80%')
  await expect(page.locator('.sales-metric').first()).toContainText('+25%')
  await expect(page.locator('.analytics-data tbody tr')).toHaveCount(25)
  await expect(page.locator('.analytics-data tbody tr').first()).toContainText(
    'Мотошлем Trail'
  )
  await page.screenshot({
    path: `${output}/analytics-light.png`,
    fullPage: true
  })
  await page.getByRole('tab', { name: 'Воронка', exact: true }).click()
  await expect(page.getByRole('tabpanel')).toBeVisible()
  await expect(page.locator('.analytics-data')).toContainText('Просмотры')
  await page.getByRole('button', { name: 'Сортировать: Заказано' }).click()
  await expect(page.locator('.analytics-data tbody tr').first()).toContainText(
    'Модель 0'
  )
  await page.getByRole('button', { name: 'Профиль и настройки' }).click()
  await page.getByRole('menuitemradio', { name: 'Тёмная', exact: true }).click()
  await page.screenshot({
    path: `${output}/analytics-dark.png`,
    fullPage: true
  })
  expect(errors).toEqual([])
})

test('period controls persist choices and reject an invalid or oversized range', async ({
  page
}) => {
  const state = await mockAnalytics(page)
  await page.goto('/analytics')
  await page.getByRole('button', { name: '14 дней', exact: true }).click()
  await expect(
    page.getByRole('button', { name: '14 дней', exact: true })
  ).toHaveAttribute('aria-pressed', 'true')
  await page.reload()
  await expect(
    page.getByRole('button', { name: '14 дней', exact: true })
  ).toHaveAttribute('aria-pressed', 'true')
  await page.getByRole('button', { name: 'Свой период', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('С', { exact: true }).fill('2024-01-29')
  await dialog.getByLabel('По', { exact: true }).fill('2027-12-31')
  const calls = state.requests.length
  await dialog.getByRole('button', { name: 'Применить', exact: true }).click()
  await expect(dialog.getByRole('alert')).toContainText(
    'Выберите завершённые дни'
  )
  expect(state.requests.length).toBe(calls)
  await dialog.getByLabel('С', { exact: true }).fill('2026-09-01')
  await dialog.getByLabel('По', { exact: true }).fill('2026-10-30')
  await dialog.getByRole('button', { name: 'Применить', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  await expect
    .poll(() =>
      state.requests.some(
        url =>
          url.searchParams.get('date_from') === '2026-09-01' &&
          url.searchParams.get('date_to') === '2026-10-30'
      )
    )
    .toBe(true)
})

test('product search, paging and metadata need no catalog permission or requests', async ({
  page,
  context
}) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  const state = await mockAnalytics(page, { analyticsOnly: true })
  await page.goto('/analytics')
  await expect(page.locator('.analytics-data tbody tr')).toHaveCount(25)
  await page
    .getByRole('button', { name: 'Следующая страница аналитики' })
    .click()
  await expect(page.locator('.analytics-data tbody tr')).toHaveCount(4)
  await page
    .getByRole('textbox', { name: 'Поиск в аналитике товаров' })
    .fill('000124')
  await expect(page.locator('.analytics-data tbody tr')).toHaveCount(1)
  await openHelmet(page)
  const dialog = page.getByRole('dialog')
  await expect(dialog).toContainText('Мотошлем Trail')
  await expect(dialog.locator('.gallery-position')).toHaveText('1 / 2')
  await dialog.getByRole('button', { name: 'Следующее фото' }).click()
  await expect(dialog.locator('.gallery-position')).toHaveText('2 / 2')
  await dialog
    .getByRole('button', { name: 'Скопировать штрихкод 000124', exact: true })
    .click()
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(
    '000124'
  )
  await expect(dialog).toContainText('+25%')
  await page.screenshot({
    path: `${output}/analytics-product.png`,
    fullPage: true
  })
  await page.keyboard.press('Escape')
  expect(state.catalogRequests).toBe(0)
  await expect(
    page
      .getByRole('navigation', { name: 'Разделы' })
      .getByRole('link', { name: 'Товары', exact: true })
  ).toHaveCount(0)
})

test('mixed cabinets keep native product identities and unavailable Ozon traffic unknown', async ({
  page
}) => {
  await mockAnalytics(page)
  await page.goto('/analytics')
  await selectStore(page, 'Все кабинеты')
  await expect(page.locator('.analytics-data tbody tr').first()).toContainText(
    'Мотоботы Track'
  )
  const total = await page
    .locator('.sales-metric')
    .first()
    .locator('strong')
    .textContent()
  await expect(
    page
      .getByRole('region', { name: 'Воронка продаж' })
      .locator('.funnel-stage')
      .first()
  ).toContainText('—')
  await page
    .getByRole('combobox', { name: 'Кабинет в таблице аналитики' })
    .selectOption(ozon)
  await expect(page.locator('.analytics-data tbody tr')).toHaveCount(1)
  await expect(
    page.locator('.sales-metric').first().locator('strong')
  ).toHaveText(total!)
  await page
    .getByRole('combobox', { name: 'Отображение артикула' })
    .selectOption('marketplace')
  await expect(page.locator('.analytics-data')).toContainText('Ozon 900124')
  await page.getByRole('tab', { name: 'Воронка', exact: true }).click()
  await expect(page.locator('.analytics-data tbody tr').first()).toContainText(
    '—'
  )
  await page.screenshot({
    path: `${output}/analytics-cabinets.png`,
    fullPage: true
  })
})

test('different currencies switch the combined view to units and preserve Ozon currency when selected', async ({
  page
}) => {
  await mockAnalytics(page, { ozonCurrency: 'KZT' })
  await page.goto('/analytics')
  await selectStore(page, 'Все кабинеты')
  await expect(
    page.getByRole('combobox', { name: 'Единицы графика' })
  ).toContainText('Количество, шт.')
  await expect(page.locator('.sales-metric').first()).toContainText('шт.')
  await page.getByRole('combobox', { name: 'Единицы графика' }).click()
  await expect(
    page.getByRole('option', { name: 'Сумма', exact: true })
  ).toHaveAttribute('data-disabled', '')
  await page.keyboard.press('Escape')
  await selectStore(page, 'PERK Test Ozon · Ozon')
  await expect(page.locator('.sales-metric').first()).toContainText('₸')
  await expect(
    page.getByRole('combobox', { name: 'Единицы графика' })
  ).toContainText('Сумма, ₸')
})

test('partial data refreshes without resetting an open product gallery', async ({
  page
}) => {
  const state = await mockAnalytics(page)
  state.partial = true
  state.summaryReady = false
  await page.goto('/analytics')
  await openHelmet(page)
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('button', { name: 'Следующее фото' }).click()
  await expect(dialog.locator('.gallery-position')).toHaveText('2 / 2')
  await expect(dialog).not.toContainText('+25%')
  state.partial = false
  state.summaryReady = true
  await expect(dialog).toContainText('+25%', { timeout: 30000 })
  await expect(dialog.locator('.gallery-position')).toHaveText('2 / 2')
  await page.keyboard.press('Escape')
  await expect(
    page.getByRole('region', { name: 'Воронка продаж' })
  ).toContainText('80%')
})

test('partial prices do not produce a growth percentage for amount totals', async ({
  page
}) => {
  const state = await mockAnalytics(page)
  state.partialAmounts = true
  await page.goto('/analytics')
  await expect(
    page.locator('.sales-metric').first().locator('.change')
  ).toContainText('—')
  await page.getByRole('combobox', { name: 'Единицы графика' }).click()
  await page
    .getByRole('option', { name: 'Количество, шт.', exact: true })
    .click()
  await expect(
    page.locator('.sales-metric').first().locator('.change')
  ).toContainText('+25%')
})

test('truncated product lists are labelled without presenting them as a full catalog', async ({
  page
}) => {
  await mockAnalytics(page, { truncated: true })
  await page.goto('/analytics')
  await expect(
    page.getByRole('heading', { name: 'Топ товаров', exact: true })
  ).toBeVisible()
  await page.getByRole('button', { name: 'О списке товаров' }).focus()
  await expect(page.getByRole('tooltip')).toContainText('первые 500')
})

test('an empty report has no invented zeroes', async ({ page }) => {
  await mockAnalytics(page, { empty: true })
  await page.goto('/analytics')
  await expect(
    page.getByText('Нет данных за период', { exact: true }).last()
  ).toBeVisible()
  await expect(page.locator('.sales-metric').first()).not.toContainText('0 ₽')
  await expect(page.locator('.analytics-data')).toHaveCount(0)
})

test('forbidden roles send no analytics requests', async ({ page }) => {
  const state = await mockAnalytics(page, { forbidden: true })
  await page.goto('/analytics')
  await expect(
    page.getByText('Нет доступа к аналитике', { exact: true })
  ).toBeVisible()
  expect(state.requests).toHaveLength(0)
})

test('errors are recoverable and a narrow window remains usable', async ({
  page
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const state = await mockAnalytics(page)
  state.fail = true
  await page.goto('/analytics')
  await expect(page.locator('.error-notice')).toBeVisible()
  state.fail = false
  await page.getByRole('button', { name: 'Обновить аналитику' }).click()
  await expect(page.locator('.analytics-data')).toBeVisible()
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth + 1
    )
  ).toBe(true)
  await page.screenshot({
    path: `${output}/analytics-narrow.png`,
    fullPage: true
  })
  await openHelmet(page)
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
})

test('home also uses neutral analytics labels and distinct Ozon SKU identities', async ({
  page
}) => {
  const state = await mockAnalytics(page, {
    analyticsOnly: true,
    twoOzon: true
  })
  await page.goto('/')
  await expect(page.locator('#reports')).toContainText('Мотошлем Trail')
  await selectStore(page, 'PERK Test Ozon · Ozon')
  const rows = page.locator('.data-table tbody tr')
  await expect(rows).toHaveCount(2)
  await expect(page.locator('#reports')).toContainText('Мотоботы Track')
  await expect(page.locator('#reports')).toContainText('OZ-123')
  expect(state.catalogRequests).toBe(0)
})

test('switching combined cabinets reuses store reports while manual refresh still reloads them', async ({
  page
}) => {
  const state = await mockAnalytics(page)
  await page.goto('/analytics')
  await expect(
    page.getByRole('button', {
      name: 'Аналитика Мотошлем Trail · WB-124',
      exact: true
    })
  ).toBeVisible()
  const requestsFor = (id: string) =>
    state.requests.filter(url => url.pathname.includes(id)).length
  const initialWB = requestsFor(wb)
  expect(initialWB).toBeGreaterThan(0)
  expect(requestsFor(ozon)).toBe(0)
  await selectStore(page, 'Все кабинеты')
  await expect(page.locator('.analytics-data tbody tr').first()).toContainText(
    'Мотоботы Track'
  )
  const initialOzon = requestsFor(ozon)
  expect(initialOzon).toBeGreaterThan(0)
  expect(requestsFor(wb)).toBe(initialWB)
  await selectStore(page, 'PERK Test Ozon · Ozon')
  await expect(page.locator('.analytics-data tbody tr')).toHaveCount(1)
  expect(requestsFor(ozon)).toBe(initialOzon)
  await selectStore(page, 'PERK Test WB · WB')
  await expect(
    page.getByRole('button', {
      name: 'Аналитика Мотошлем Trail · WB-124',
      exact: true
    })
  ).toBeVisible()
  expect(requestsFor(wb)).toBe(initialWB)
  await page
    .getByRole('button', { name: 'Обновить аналитику', exact: true })
    .click()
  await expect.poll(() => requestsFor(wb)).toBeGreaterThan(initialWB)
})
