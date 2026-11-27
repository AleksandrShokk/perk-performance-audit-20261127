import { expect, test } from '@playwright/test'
import { readFile } from 'node:fs/promises'

import { ozon, wb } from './fixtures'
import { mockPlanner } from './supply-planner-fixtures'

const output =
  'C:/Users/Artem/Documents/ChatGPT/PERK/outputs/web-supply-planner-20261106'
test('planning parameters apply on submit, persist, and keep summary independent of list filters', async ({
  page
}) => {
  const state = await mockPlanner(page)
  await page.goto('/supplies')
  await expect(page.locator('.supply-data tbody tr')).toHaveCount(20)
  await page.getByLabel('Запас после поступления, дней').fill('60')
  await page.getByLabel('Доставка и приёмка, дней').fill('0')
  expect(
    state.requests.every(url => url.searchParams.get('target_days') === '30')
  ).toBe(true)
  await page.getByRole('button', { name: 'Рассчитать', exact: true }).click()
  await expect(page.locator('.supply-target')).toContainText('60 дней')
  expect(
    state.requests.some(
      url =>
        url.searchParams.get('target_days') === '60' &&
        url.searchParams.get('lead_time_days') === '0'
    )
  ).toBe(true)
  await page.reload()
  await expect(page.getByLabel('Запас после поступления, дней')).toHaveValue(
    '60'
  )
  await expect(page.getByLabel('Доставка и приёмка, дней')).toHaveValue('0')
  await page.getByRole('combobox', { name: 'Выбрать кабинет' }).click()
  await page.getByRole('option', { name: 'Все кабинеты', exact: true }).click()
  const summary = page.getByRole('region', {
    name: 'Общая потребность в поставке'
  })
  const total = await summary.innerText()
  await page
    .getByRole('combobox', { name: 'Кабинет в списке поставок' })
    .selectOption(ozon)
  await expect(page.locator('.supply-data tbody tr')).toHaveCount(1)
  expect(await summary.innerText()).toBe(total)
})

test('packaging is stored per cabinet, refreshes quantities and survives reopening', async ({
  page
}) => {
  const state = await mockPlanner(page)
  await page.goto('/supplies')
  await page
    .getByRole('button', { name: 'Кратность Мотошлем 0 · WB-0', exact: true })
    .click()
  await page.getByLabel('Товаров в коробе').fill('5')
  await page
    .getByRole('button', { name: 'Сохранить кратность', exact: true })
    .click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.locator('.supply-data tbody tr').first()).toContainText(
    '65 шт.'
  )
  expect(state.writes).toEqual([
    { store: wb, key: 'product-0', box_multiple: 5 }
  ])
  await page
    .getByRole('button', { name: 'Кратность Мотошлем 0 · WB-0', exact: true })
    .click()
  await expect(page.getByLabel('Товаров в коробе')).toHaveValue('5')
  await page.keyboard.press('Escape')
  await page.screenshot({ path: output + '/planner.png', fullPage: true })
  expect(state.csrfValid).toBe(true)
})

test('Ozon packaging uses its native product identity and stays separate from WB', async ({
  page
}) => {
  const state = await mockPlanner(page)
  await page.goto('/supplies')
  await page.getByRole('combobox', { name: 'Выбрать кабинет' }).click()
  await page
    .getByRole('option', { name: 'PERK Test Ozon · Ozon', exact: true })
    .click()
  await page
    .getByRole('button', { name: 'Кратность Мотоботы 0 · OZ-0', exact: true })
    .click()
  await page.getByLabel('Товаров в коробе').fill('6')
  await page
    .getByRole('button', { name: 'Сохранить кратность', exact: true })
    .click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  expect(state.writes[0]).toEqual({
    store: ozon,
    key: 'product-0',
    box_multiple: 6
  })
  await page.getByRole('combobox', { name: 'Выбрать кабинет' }).click()
  await page.getByRole('option', { name: 'PERK Test WB · WB', exact: true }).click()
  await expect(
    page.getByRole('button', {
      name: 'Кратность Мотошлем 0 · WB-0',
      exact: true
    })
  ).toHaveText('1')
})

test('export downloads every page with the current parameters and cabinet filter', async ({
  page
}) => {
  const state = await mockPlanner(page)
  await page.goto('/supplies')
  await expect(page.locator('.supply-data tbody tr')).toHaveCount(20)
  const saved = page.waitForEvent('download')
  await page
    .getByRole('button', { name: 'Выгрузить потребность', exact: true })
    .click()
  const file = await saved
  const content = await readFile((await file.path())!, 'utf8')
  expect(content).toContain('WB-23')
  expect(content).not.toContain('OZ-0')
  expect(
    state.requests.filter(url => url.pathname.endsWith('/export'))
  ).toHaveLength(1)
  await page.getByRole('combobox', { name: 'Выбрать кабинет' }).click()
  await page.getByRole('option', { name: 'Все кабинеты', exact: true }).click()
  await page
    .getByRole('combobox', { name: 'Кабинет в списке поставок' })
    .selectOption(ozon)
  const second = page.waitForEvent('download')
  await page
    .getByRole('button', { name: 'Выгрузить потребность', exact: true })
    .click()
  await second
  const request = state.requests
    .filter(url => url.pathname.endsWith('/export'))
    .at(-1)!
  expect(request.searchParams.get('store_id')).toBe(ozon)
  expect(request.searchParams.get('target_days')).toBe('30')
  expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toContain(
    'Мотошлем'
  )
})

test('read-only staff can calculate but cannot configure packaging or export', async ({
  page
}) => {
  await mockPlanner(page, 'viewer')
  await page.goto('/supplies')
  await expect(page.getByLabel('Запас после поступления, дней')).toBeVisible()
  await expect(page.getByRole('button', { name: /^Кратность / })).toHaveCount(0)
  await expect(
    page.getByRole('button', { name: 'Выгрузить потребность', exact: true })
  ).toHaveCount(0)
})

test('closing a failed or pending packaging edit keeps a new dialog usable', async ({
  page
}) => {
  const state = await mockPlanner(page)
  await page.goto('/supplies')
  await page
    .getByRole('button', { name: 'Кратность Мотошлем 0 · WB-0', exact: true })
    .click()
  state.failSave = true
  await page.getByLabel('Товаров в коробе').fill('5')
  await page
    .getByRole('button', { name: 'Сохранить кратность', exact: true })
    .click()
  await expect(page.getByRole('dialog').locator('.error-notice')).toContainText(
    'Не удалось сохранить кратность'
  )
  state.failSave = false
  state.holdSave = true
  await page
    .getByRole('button', { name: 'Сохранить кратность', exact: true })
    .click()
  await expect.poll(() => state.releaseSave !== null).toBe(true)
  await page.keyboard.press('Escape')
  await page
    .getByRole('button', { name: 'Кратность Мотошлем 1 · WB-1', exact: true })
    .click()
  state.releaseSave?.()
  await expect(page.getByLabel('Товаров в коробе')).toHaveValue('1')
  await page.getByLabel('Товаров в коробе').fill('6')
  await expect(page.getByLabel('Товаров в коробе')).toBeEditable()
})

test('planner remains within a narrow screen after changing parameters', async ({
  page
}) => {
  await mockPlanner(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/supplies')
  await expect(page.locator('.supply-data tbody tr')).toHaveCount(20)
  await page.getByLabel('Запас после поступления, дней').fill('14')
  await page.getByRole('button', { name: 'Рассчитать', exact: true }).click()
  await expect(page.locator('.supply-target')).toContainText('14 дней')
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth
    )
  ).toBe(true)
  await page.screenshot({
    path: output + '/planner-mobile.png',
    fullPage: true
  })
})
