import { expect, test } from '@playwright/test'

import { mockFinance } from './finance-fixtures'
import { ozon } from './fixtures'

const output =
  'C:/Users/Artem/Documents/ChatGPT/PERK/outputs/web-finance-20261105'

test('finance shows exact API totals, details, long periods, combined stores and export', async ({
  page
}) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  const state = await mockFinance(page)
  await page.goto('/finance')
  await expect(page.locator('.finance-page-summary')).toContainText(
    '1\u00a0284\u00a0600,27 ₽'
  )
  await expect(page.locator('.finance-ledger')).toContainText('342 шт.')
  await page
    .getByRole('button', { name: 'Развернуть всё', exact: true })
    .click()
  await expect(
    page.getByRole('button', { name: 'Комиссия и эквайринг', exact: true })
  ).toHaveAttribute('aria-expanded', 'true')
  await page.screenshot({ path: `${output}/finance-light.png`, fullPage: true })
  await page.getByRole('button', { name: '90 дней', exact: true }).click()
  await expect(
    page.getByRole('button', { name: '90 дней', exact: true })
  ).toHaveAttribute('aria-pressed', 'true')
  await page.getByRole('button', { name: 'Свой период', exact: true }).click()
  const dates = page.getByRole('dialog')
  await dates.getByLabel('С', { exact: true }).fill('2025-01-01')
  await dates.getByLabel('По', { exact: true }).fill('2026-10-28')
  await dates.getByRole('button', { name: 'Применить', exact: true }).click()
  await expect
    .poll(() =>
      state.paths.some(
        path =>
          path.includes('date_from=2025-01-01') &&
          path.includes('date_to=2026-10-28')
      )
    )
    .toBe(true)
  await page.reload()
  await expect(
    page.getByRole('button', { name: /1 января 2025/ })
  ).toBeVisible()
  await page.getByRole('combobox', { name: 'Выбрать кабинет' }).click()
  await page.getByRole('option', { name: 'Все кабинеты', exact: true }).click()
  await expect(page.locator('.finance-page-summary')).toContainText(
    '3\u00a0853\u00a0800,81 ₽'
  )
  const downloadEvent = page.waitForEvent('download')
  await page
    .getByRole('button', { name: 'Скачать сводку', exact: true })
    .click()
  expect((await downloadEvent).suggestedFilename()).toBe(
    'perk-finance-2025-01-01-2026-10-28.csv'
  )
  await page.getByRole('button', { name: 'Профиль и настройки' }).click()
  await page.getByRole('menuitemradio', { name: 'Тёмная', exact: true }).click()
  await page.screenshot({ path: `${output}/finance-dark.png`, fullPage: true })
  expect(errors).toEqual([])
})

test('expense validation, idempotent retry, refreshed totals and deletion work', async ({
  page
}) => {
  const state = await mockFinance(page, { failFirstExpense: true })
  await page.goto('/finance')
  await page
    .getByRole('button', { name: 'Добавить расход', exact: true })
    .click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Сумма, RUB').fill('0')
  await dialog.getByLabel('За что расход').fill('Упаковка тест')
  await dialog.getByRole('button', { name: 'Сохранить расход' }).click()
  await expect(dialog.getByRole('alert')).toContainText('больше нуля')
  expect(state.requestIds).toHaveLength(0)
  await dialog.getByLabel('Сумма, RUB').fill('1500,50')
  await dialog.getByRole('combobox', { name: 'Категория расхода' }).click()
  await page.getByRole('option', { name: 'Упаковка', exact: true }).click()
  await dialog.getByRole('button', { name: 'Сохранить расход' }).click()
  await expect(dialog.getByRole('alert')).toContainText('Временная ошибка')
  await dialog.getByRole('button', { name: 'Сохранить расход' }).click()
  await expect(dialog).toHaveCount(0)
  expect(state.requestIds).toHaveLength(2)
  expect(state.requestIds[0]).toBe(state.requestIds[1])
  expect(state.expenses).toHaveLength(1)
  expect(state.csrf).toBe(true)
  await expect(page.locator('.finance-page-summary')).toContainText(
    '435\u00a0000,67 ₽'
  )
  await page.getByRole('button', { name: 'История внешних расходов' }).click()
  await expect(dialog).toContainText('Упаковка тест')
  await dialog
    .getByRole('button', { name: 'Удалить расход «Упаковка тест»' })
    .click()
  await dialog.getByRole('button', { name: 'Удалить', exact: true }).click()
  await expect(dialog).toContainText('Внешних расходов пока нет')
  expect(state.deleted).toHaveLength(1)
  await page.keyboard.press('Escape')
  await expect(page.locator('.finance-page-summary')).toContainText(
    '433\u00a0500,17 ₽'
  )
})

test('tax settings load and save to the selected cabinet', async ({ page }) => {
  const state = await mockFinance(page)
  await page.goto('/finance')
  await page
    .getByRole('button', { name: 'Настроить налоги', exact: true })
    .click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByLabel('Ставка налога, %')).toHaveValue('6')
  await dialog.getByLabel('Ставка налога, %').fill('7,25')
  await dialog.getByLabel('Действует с').fill('2026-10-01')
  await dialog.getByRole('button', { name: 'Сохранить настройки' }).click()
  await expect(dialog).toHaveCount(0)
  expect(state.taxWrites[0]).toMatchObject({
    effective_from: '2026-10-01',
    rate: '7.25',
    vat_rate: '0',
    regime: 'usn_income'
  })
  expect(state.csrf).toBe(true)
})

test('cost imports require explicit cabinet and preview before apply, including Ozon', async ({
  page
}) => {
  const state = await mockFinance(page)
  await page.goto('/finance')
  await page.getByRole('combobox', { name: 'Выбрать кабинет' }).click()
  await page.getByRole('option', { name: 'Все кабинеты', exact: true }).click()
  await page
    .locator('.finance-actions')
    .getByRole('button', { name: 'Себестоимость', exact: true })
    .click()
  const dialog = page.getByRole('dialog')
  await expect(
    dialog.getByRole('button', { name: 'Загрузить файл', exact: true })
  ).toHaveCount(0)
  await dialog.getByLabel('Кабинет', { exact: true }).selectOption(ozon)
  const downloadEvent = page.waitForEvent('download')
  await dialog.getByRole('button', { name: 'Скачать шаблон XLSX' }).click()
  expect((await downloadEvent).suggestedFilename()).toBe('perk-costs.xlsx')
  expect(state.templates[0]).toContain(ozon)
  const file = dialog.getByLabel('Файл себестоимости')
  await file.setInputFiles({
    name: 'invalid.xlsx',
    mimeType:
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    buffer: Buffer.from('test only')
  })
  await expect(dialog).toContainText('Не найдена себестоимость')
  await expect(
    dialog.getByRole('button', { name: 'Применить себестоимость', exact: true })
  ).toBeDisabled()
  expect(state.applied).toHaveLength(0)
  await file.setInputFiles({
    name: 'valid.xlsx',
    mimeType:
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    buffer: Buffer.from('test only')
  })
  await expect(dialog).toContainText('OZ-001')
  await expect(dialog).toContainText('1250,1234')
  await dialog
    .getByRole('button', { name: 'Применить себестоимость', exact: true })
    .click()
  await expect(dialog).toHaveCount(0)
  expect(state.previews.every(path => path.includes(ozon))).toBe(true)
  expect(state.applied[0]).toContain(ozon)
  expect(state.multipart).toBe(true)
  expect(state.csrf).toBe(true)
})

test('finance-only roles do not see profit, costs or write actions, and narrow view fits', async ({
  page
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mockFinance(page, { profit: false })
  await page.goto('/finance')
  await expect(
    page.getByRole('heading', { name: 'Доходы и расходы', exact: true })
  ).toBeVisible()
  await expect(
    page.getByText('Прибыль до налогов', { exact: true })
  ).toHaveCount(0)
  await expect(
    page
      .locator('.finance-actions')
      .getByRole('button', { name: 'Себестоимость', exact: true })
  ).toHaveCount(0)
  await expect(
    page.getByRole('button', { name: 'Добавить расход', exact: true })
  ).toHaveCount(0)
  await expect(
    page.getByRole('heading', { name: 'Налоги', exact: true })
  ).toHaveCount(0)
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth
    )
  ).toBe(true)
  await expect(
    page.locator('.finance-group-row').first().locator('td').last()
  ).toBeInViewport({ ratio: 0.9 })
  await page.screenshot({
    path: `${output}/finance-narrow.png`,
    fullPage: true
  })
})

test('closing a pending expense keeps the page interactive and its late result does not close a new dialog', async ({
  page
}) => {
  let release!: () => void
  const gate = new Promise<void>(resolve => {
    release = resolve
  })
  await mockFinance(page, { holdExpense: gate })
  await page.goto('/finance')
  await page
    .getByRole('button', { name: 'Добавить расход', exact: true })
    .click()
  await page.getByLabel('Сумма, RUB').fill('10')
  await page.getByLabel('За что расход').fill('Отложенный тест')
  const sent = page.waitForRequest(
    request =>
      request.method() === 'POST' && request.url().endsWith('/expenses')
  )
  await page
    .getByRole('button', { name: 'Сохранить расход', exact: true })
    .click()
  await sent
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page
    .getByRole('button', { name: 'Добавить расход', exact: true })
    .click()
  release()
  await expect(page.locator('.finance-saved')).toContainText('Сохранено')
  await expect(page.getByRole('dialog')).toBeVisible()
  await expect(page.getByLabel('За что расход')).toHaveValue('')
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: 'Профиль и настройки' }).click()
  await expect(
    page.getByRole('menuitem', { name: 'Выйти из аккаунта' })
  ).toBeVisible()
})

test('partial report polling updates figures without remounting the opened report', async ({
  page
}) => {
  const state = await mockFinance(page, { partial: true })
  await page.goto('/finance')
  await expect(page.getByLabel('Финансовые данные загружаются')).toBeVisible()
  await page
    .getByRole('button', { name: 'Комиссия и эквайринг', exact: true })
    .click()
  await page
    .locator('#ledger-title')
    .evaluate(node => node.setAttribute('data-stable', 'yes'))
  await expect
    .poll(() => state.reportCalls, { timeout: 12000 })
    .toBeGreaterThanOrEqual(2)
  await expect(page.getByLabel('Финансовые данные загружаются')).toHaveCount(0)
  await expect(page.locator('#ledger-title')).toHaveAttribute(
    'data-stable',
    'yes'
  )
  await expect(
    page.getByRole('button', { name: 'Комиссия и эквайринг', exact: true })
  ).toHaveAttribute('aria-expanded', 'true')
})

test('an empty report has an explicit state and does not invent zero amounts', async ({
  page
}) => {
  await mockFinance(page, { empty: true })
  await page.goto('/finance')
  await expect(
    page.getByText('Нет финансовых данных за период', { exact: true })
  ).toBeVisible()
  await expect(page.locator('.finance-ledger')).toHaveCount(0)
  await expect(page.locator('.finance-page-summary')).not.toContainText('0,00')
  await expect(
    page.getByRole('button', { name: 'Добавить расход', exact: true })
  ).toBeEnabled()
})
