import { expect, test } from '@playwright/test'
import { readFile } from 'node:fs/promises'

import { ozon, wb } from './fixtures'
import { mockPlans } from './supply-plans-fixtures'

const output =
  'C:/Users/Artem/Documents/ChatGPT/PERK/outputs/web-supply-plans-20261106'

test('create an empty cabinet plan and add only selected products', async ({
  page
}) => {
  const state = await mockPlans(page)
  await page.goto('/supplies')
  await page.getByRole('button', { name: 'Создать план', exact: true }).click()
  await page.getByLabel('Название плана').fill('Поставка шлемов')
  await page.getByLabel('Склад / кластер', { exact: true }).fill('Коледино')
  await page
    .getByRole('dialog')
    .getByRole('button', { name: 'Создать план', exact: true })
    .click()
  await expect(
    page.getByRole('dialog').getByLabel('Название плана')
  ).toHaveValue('Поставка шлемов')
  await expect(page.getByRole('dialog')).toContainText('План пуст')
  expect(state.plans[0]!.items).toHaveLength(0)
  await page
    .getByRole('button', { name: 'Добавить товары', exact: true })
    .click()
  await page.getByRole('checkbox').first().check()
  await page
    .getByRole('button', { name: 'Добавить выбранные · 1', exact: true })
    .click()
  await expect(page.getByLabel('К поставке WB-0', { exact: true })).toHaveValue(
    '0'
  )
  expect(state.plans[0]!.items).toHaveLength(1)
  expect(state.creates[0]!.store).toBe(wb)
  await page.keyboard.press('Escape')
  await expect(
    page.getByRole('region', { name: 'Сохранённые планы' })
  ).toContainText('Поставка шлемов')
  await page.reload()
  await page.getByRole('tab', { name: 'Планы', exact: true }).click()
  await page
    .getByRole('button', { name: 'Поставка шлемов', exact: true })
    .click()
  await expect(page.getByLabel('Склад / кластер', { exact: true })).toHaveValue(
    'Коледино'
  )
  expect(state.csrfValid).toBe(true)
})

test('edit quantities across pages, preserve recommendations and exclude zeroes from export', async ({
  page
}) => {
  const state = await mockPlans(page),
    plan = state.seed()
  await page.goto('/supplies')
  await page.getByRole('tab', { name: 'Планы', exact: true }).click()
  await page.getByRole('button', { name: plan.title, exact: true }).click()
  await page.getByLabel('К поставке WB-0', { exact: true }).fill('100')
  await expect(page.getByRole('button', { name: 'Скачать CSV' })).toBeDisabled()
  await page
    .getByRole('dialog')
    .getByRole('button', { name: 'Следующая страница поставок' })
    .click()
  await page.getByLabel('К поставке WB-23', { exact: true }).fill('0')
  await page.getByLabel('Статус плана').selectOption('ready')
  await page
    .getByRole('button', { name: 'Сохранить план', exact: true })
    .click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  expect(state.writes[0]!.items).toHaveLength(24)
  expect(state.writes[0]!.items[0]!.quantity).toBe(100)
  expect(state.writes[0]!.items[23]!.quantity).toBe(0)
  await page.getByRole('button', { name: plan.title, exact: true }).click()
  await expect(page.getByLabel('К поставке WB-0', { exact: true })).toHaveValue(
    '100'
  )
  await expect(
    page.getByRole('dialog').locator('tbody tr').first()
  ).toContainText('65 шт.')
  await page.getByLabel('Поиск в плане').fill('WB-23')
  await expect(page.getByRole('dialog').locator('tbody tr')).toHaveCount(1)
  await expect(
    page.getByLabel('К поставке WB-23', { exact: true })
  ).toHaveValue('0')
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button', { name: 'Скачать CSV' }).click()
  ])
  const content = await readFile((await download.path())!, 'utf8')
  expect(content).toContain('"WB-0";"100"')
  expect(content).not.toContain('WB-23')
  await page.getByLabel('Поиск в плане').fill('')
  await page.screenshot({ path: output + '/plan-editor.png', fullPage: true })
})

test('cabinet selection keeps WB and Ozon plans separate', async ({ page }) => {
  const state = await mockPlans(page)
  state.seed(wb, 'План WB')
  state.seed(ozon, 'План Ozon')
  await page.goto('/supplies')
  await page.getByRole('combobox', { name: 'Выбрать кабинет' }).click()
  await page.getByRole('option', { name: 'Все кабинеты', exact: true }).click()
  await page.getByRole('tab', { name: 'Планы', exact: true }).click()
  await expect(
    page.getByRole('region', { name: 'Сохранённые планы' }).locator('tbody tr')
  ).toHaveCount(2)
  await page.getByLabel('Кабинет в списке поставок').selectOption(ozon)
  await expect(
    page.getByRole('region', { name: 'Сохранённые планы' }).locator('tbody tr')
  ).toHaveCount(1)
  await page.getByRole('button', { name: 'План Ozon', exact: true }).click()
  await expect(
    page.getByLabel('К поставке OZ-0', { exact: true })
  ).toBeVisible()
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: 'Новый план', exact: true }).click()
  await expect(page.getByLabel('Кабинет для плана')).toHaveValue(ozon)
})

test('read-only employees can inspect plans without editing or export rights', async ({
  page
}) => {
  const state = await mockPlans(page, 'viewer'),
    plan = state.seed()
  await page.goto('/supplies')
  await expect(
    page.getByRole('button', { name: 'Создать план', exact: true })
  ).toHaveCount(0)
  await page.getByRole('tab', { name: 'Планы', exact: true }).click()
  await expect(
    page.getByRole('button', { name: 'Новый план', exact: true })
  ).toHaveCount(0)
  await page.getByRole('button', { name: plan.title, exact: true }).click()
  await expect(
    page.getByLabel('К поставке WB-0', { exact: true })
  ).toBeDisabled()
  await expect(
    page.getByRole('button', { name: 'Сохранить план', exact: true })
  ).toHaveCount(0)
  await expect(
    page.getByRole('button', { name: 'Скачать CSV', exact: true })
  ).toHaveCount(0)
})

test('server conflict leaves edits visible without replacing another revision', async ({
  page
}) => {
  const state = await mockPlans(page),
    plan = state.seed()
  state.conflict = true
  await page.goto('/supplies')
  await page.getByRole('tab', { name: 'Планы', exact: true }).click()
  await page.getByRole('button', { name: plan.title, exact: true }).click()
  await page.getByLabel('К поставке WB-0', { exact: true }).fill('100')
  await page
    .getByRole('button', { name: 'Сохранить план', exact: true })
    .click()
  await expect(page.getByRole('dialog')).toContainText('План уже изменён')
  await expect(page.getByLabel('К поставке WB-0', { exact: true })).toHaveValue(
    '100'
  )
  expect(state.plans[0]!.items[0]!.quantity).toBe(65)
})

test('closing a pending save releases the page and ignores a late response', async ({
  page
}) => {
  const state = await mockPlans(page),
    plan = state.seed()
  state.hold = true
  await page.goto('/supplies')
  await page.getByRole('tab', { name: 'Планы', exact: true }).click()
  await page.getByRole('button', { name: plan.title, exact: true }).click()
  await page.getByLabel('К поставке WB-0', { exact: true }).fill('100')
  await page
    .getByRole('button', { name: 'Сохранить план', exact: true })
    .click()
  await expect(
    page.getByRole('button', { name: 'Сохраняем…', exact: true })
  ).toBeDisabled()
  await page.keyboard.press('Escape')
  await page.getByRole('tab', { name: 'Рекомендации', exact: true }).click()
  state.release?.()
  await expect(
    page.getByRole('button', { name: 'Рассчитать', exact: true })
  ).toBeVisible()
  await expect(page.getByRole('dialog')).toHaveCount(0)
})

test('plan editor fits a narrow viewport and keeps actions reachable', async ({
  page
}) => {
  const state = await mockPlans(page),
    plan = state.seed()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/supplies')
  await page.getByRole('tab', { name: 'Планы', exact: true }).click()
  await page.getByRole('button', { name: plan.title, exact: true }).click()
  await expect(
    page.getByRole('heading', { name: 'План поставки', exact: true })
  ).toBeInViewport()
  await expect
    .poll(() =>
      page
        .getByRole('dialog')
        .evaluate(element => element.scrollWidth <= element.clientWidth)
    )
    .toBe(true)
  await page
    .getByRole('button', { name: 'Скачать CSV', exact: true })
    .scrollIntoViewIfNeeded()
  await expect(
    page.getByRole('button', { name: 'Скачать CSV', exact: true })
  ).toBeInViewport()
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth
    )
  ).toBe(true)
  await page.screenshot({ path: output + '/plan-mobile.png', fullPage: true })
})
