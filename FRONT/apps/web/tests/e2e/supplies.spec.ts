import { type Page, expect, test } from '@playwright/test'

import { ozon } from './fixtures'
import { mockSupplies } from './supplies-fixtures'

const output =
  'C:/Users/Artem/Documents/ChatGPT/PERK/outputs/web-supplies-20261106'
async function selectStore(page: Page, name: string) {
  await page.getByRole('combobox', { name: 'Выбрать кабинет' }).click()
  await page.getByRole('option', { name, exact: true }).click()
}
const openHelmet = (page: Page) =>
  page
    .getByRole('button', {
      name: 'Рекомендация Мотошлем Trail · WB-0',
      exact: true
    })
    .click()

test('recommendations use server pages and identifiers without fetching supply history prematurely', async ({
  page
}) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  const state = await mockSupplies(page)
  await page.goto('/supplies')
  await expect(page.locator('.supply-data tbody tr')).toHaveCount(20)
  await expect(
    page.getByRole('region', { name: 'Общая потребность в поставке' })
  ).toContainText('500 шт.')
  expect(
    state.requests.filter(url => url.pathname.endsWith('/supplies'))
  ).toHaveLength(0)
  await page.screenshot({
    path: `${output}/supplies-light.png`,
    fullPage: true
  })
  await page
    .getByRole('button', { name: 'Следующая страница поставок' })
    .click()
  await expect(page.locator('.supply-data tbody tr')).toHaveCount(4)
  expect(
    state.requests.some(url => url.searchParams.get('offset') === '20')
  ).toBe(true)
  await page
    .getByRole('button', { name: 'Предыдущая страница поставок' })
    .click()
  await page
    .getByRole('combobox', { name: 'Отображение артикула' })
    .selectOption('barcode')
  await expect(page.locator('.supply-data tbody tr').first()).toContainText(
    '000100'
  )
  await page.reload()
  await expect(
    page.getByRole('combobox', { name: 'Отображение артикула' })
  ).toHaveValue('barcode')
  await page.getByRole('button', { name: 'Профиль и настройки' }).click()
  await page.getByRole('menuitemradio', { name: 'Тёмная', exact: true }).click()
  await page.screenshot({ path: `${output}/supplies-dark.png`, fullPage: true })
  expect(errors).toEqual([])
})

test('the list cabinet filter and urgency do not change the whole-business need', async ({
  page
}) => {
  const state = await mockSupplies(page)
  await page.goto('/supplies')
  await selectStore(page, 'Все кабинеты')
  const summary = page.getByRole('region', {
    name: 'Общая потребность в поставке'
  })
  await expect(summary).toContainText('1 400 шт.')
  await page
    .getByRole('combobox', { name: 'Кабинет в списке поставок' })
    .selectOption(ozon)
  await expect(page.locator('.supply-data tbody tr')).toHaveCount(1)
  await expect(page.locator('.supply-data')).toContainText('Мотоботы Track')
  await expect(summary).toContainText('1 400 шт.')
  await expect(
    page.getByRole('combobox', { name: 'Выбрать кабинет' })
  ).toContainText('Все кабинеты')
  await page.getByRole('button', { name: 'Срочные', exact: true }).click()
  await expect(
    page.getByRole('button', { name: 'Срочные', exact: true })
  ).toHaveAttribute('aria-pressed', 'true')
  await expect(summary).toContainText('1 400 шт.')
  await summary.getByRole('button', { name: /Срочных позиций/ }).click()
  await expect(
    page.getByRole('combobox', { name: 'Кабинет в списке поставок' })
  ).toHaveValue('all')
  await expect(page.locator('.supply-data tbody tr')).toHaveCount(9)
  expect(
    state.requests
      .filter(url => url.searchParams.get('limit') === '0')
      .every(url => url.searchParams.get('urgent_only') !== 'true')
  ).toBe(true)
})

test('recommendation details show native demand, photo and copyable barcode', async ({
  page,
  context
}) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  await mockSupplies(page)
  await page.goto('/supplies')
  await openHelmet(page)
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('img')).toBeVisible()
  await expect(dialog).toContainText('150 шт.')
  await expect(dialog).toContainText('Заказов в день')
  await expect(dialog).toContainText('2,5')
  await dialog
    .getByRole('button', { name: 'Скопировать штрихкод 000100', exact: true })
    .click()
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(
    '000100'
  )
  await page.screenshot({
    path: `${output}/recommendation-details.png`,
    fullPage: true
  })
  await page.keyboard.press('Escape')
  await selectStore(page, 'PERK Test Ozon · Ozon')
  await page
    .getByRole('button', { name: 'Рекомендация Мотоботы Track · OZ-0' })
    .click()
  await expect(dialog).toContainText('Продаж в день')
  await expect(dialog).toContainText('900100')
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: 'Обновить поставки' }).click()
  await expect(
    page.getByRole('button', { name: 'Обновить поставки' })
  ).toBeEnabled()
})

test('placed supplies preserve rejected status, missing values and native Ozon applications', async ({
  page
}) => {
  const state = await mockSupplies(page)
  await page.goto('/supplies')
  await page.getByRole('tab', { name: 'Оформленные', exact: true }).click()
  await expect(
    page.getByRole('region', { name: 'Оформленные поставки' })
  ).toBeVisible()
  await expect(page.locator('.supply-data')).toContainText('Отклонена')
  await expect(page.locator('.supply-data')).toContainText('Статус уточняется')
  await page
    .getByRole('button', { name: 'Открыть Поставка №101', exact: true })
    .click()
  const dialog = page.getByRole('dialog')
  await expect(
    dialog.locator('.supply-detail-value').filter({ hasText: 'В поставке' })
  ).toContainText('—')
  await expect(
    dialog.locator('.supply-detail-value').filter({ hasText: 'Принято' })
  ).toContainText('0 шт.')
  await expect(dialog).toContainText('6 нояб. 2026')
  await page.keyboard.press('Escape')
  await page
    .getByRole('button', { name: 'Следующая страница поставок' })
    .click()
  await expect(page.locator('.supply-data tbody tr')).toHaveCount(4)
  await selectStore(page, 'Все кабинеты')
  await page.getByRole('tab', { name: 'Оформленные', exact: true }).click()
  await page
    .getByRole('combobox', { name: 'Кабинет в списке поставок' })
    .selectOption(ozon)
  await expect(page.locator('.supply-data tbody tr')).toHaveCount(1)
  await page
    .getByRole('button', { name: 'Открыть Заявка №ОЗ-001', exact: true })
    .click()
  await expect(dialog).toContainText('Идёт приёмка')
  await expect(dialog).toContainText('Москва и МО')
  await page.screenshot({
    path: `${output}/placed-details.png`,
    fullPage: true
  })
  expect(state.methods.every(method => method === 'GET')).toBe(true)
})

test('background updates preserve an open recommendation', async ({ page }) => {
  const state = await mockSupplies(page)
  state.loading = true
  await page.goto('/supplies')
  await openHelmet(page)
  const requests = state.requests.length
  await expect
    .poll(() => state.requests.length, { timeout: 15000 })
    .toBeGreaterThan(requests)
  await expect(page.getByRole('dialog')).toBeVisible()
  await expect(page.getByRole('dialog')).toContainText('Мотошлем Trail')
  state.loading = false
  await page.keyboard.press('Escape')
  await expect(page.getByRole('textbox')).toHaveCount(0)
  await page.getByRole('tab', { name: 'Оформленные', exact: true }).click()
  await expect(
    page.getByRole('region', { name: 'Оформленные поставки' })
  ).toBeVisible()
})

test('no-demand and unknown-demand states are not confused', async ({
  page
}) => {
  await mockSupplies(page, { empty: true })
  await page.goto('/supplies')
  await expect(
    page.getByText('Пополнение не требуется', { exact: true })
  ).toBeVisible()
  await expect(
    page.getByRole('region', { name: 'Общая потребность в поставке' })
  ).toContainText('0 шт.')
  await page.getByRole('tab', { name: 'Оформленные', exact: true }).click()
  await expect(
    page.getByText('Оформленных поставок пока нет', { exact: true })
  ).toBeVisible()
})

test('missing source data has an explicit state without invented zero need', async ({
  page
}) => {
  await mockSupplies(page, { noData: true })
  await page.goto('/supplies')
  await expect(
    page.getByText('Расчёт ещё не готов', { exact: true })
  ).toBeVisible()
  await expect(
    page.getByRole('region', { name: 'Общая потребность в поставке' })
  ).not.toContainText('0 шт.')
})

test('missing token access and network errors remain recoverable', async ({
  page
}) => {
  const state = await mockSupplies(page)
  await page.goto('/supplies')
  state.missingAccess = true
  await page.getByRole('tab', { name: 'Оформленные', exact: true }).click()
  await expect(page.locator('.error-notice')).toContainText(
    'Проверьте права на поставки'
  )
  state.missingAccess = false
  await page.getByRole('button', { name: 'Повторить', exact: true }).click()
  await expect(
    page.getByRole('region', { name: 'Оформленные поставки' })
  ).toBeVisible()
  state.fail = true
  await page.getByRole('button', { name: 'Обновить поставки' }).click()
  await expect(page.locator('.error-notice').first()).toBeVisible()
  state.fail = false
  await page.getByRole('button', { name: 'Обновить поставки' }).click()
  await expect(page.locator('.error-notice')).toHaveCount(0)
})

test('roles without inventory access issue no supply queries', async ({
  page
}) => {
  const state = await mockSupplies(page, { role: 'accountant' })
  await page.goto('/supplies')
  await expect(
    page.getByText('Нет доступа к поставкам', { exact: true })
  ).toBeVisible()
  expect(state.requests).toHaveLength(0)
  await expect(
    page
      .getByRole('navigation', { name: 'Разделы' })
      .getByRole('link', { name: 'Поставки', exact: true })
  ).toHaveCount(0)
})

test('a history-only connection does not request unsupported recommendations', async ({
  page
}) => {
  const state = await mockSupplies(page, { historyOnly: true })
  await page.goto('/supplies')
  await expect(
    page.getByRole('region', { name: 'Оформленные поставки' })
  ).toBeVisible()
  await expect(
    page.getByRole('tab', { name: 'Рекомендации', exact: true })
  ).toHaveCount(0)
  expect(
    state.requests.filter(url => url.pathname.endsWith('/replenishment'))
  ).toHaveLength(0)
})

test('narrow viewport fits and cabinet switching closes private details', async ({
  page
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mockSupplies(page, { role: 'viewer' })
  await page.goto('/supplies')
  await expect(page.locator('.supply-data')).toBeVisible()
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth + 1
    )
  ).toBe(true)
  await page.screenshot({
    path: `${output}/supplies-narrow.png`,
    fullPage: true
  })
  await openHelmet(page)
  await page.keyboard.press('Escape')
  await page.getByRole('tab', { name: 'Оформленные', exact: true }).click()
  await page
    .getByRole('button', { name: 'Открыть Поставка №101', exact: true })
    .click()
  await page.keyboard.press('Escape')
  await selectStore(page, 'PERK Test Ozon · Ozon')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(
    page.getByRole('region', { name: 'Общая потребность в поставке' })
  ).toContainText('900 шт.')
})
