import { expect, test } from '@playwright/test'
import { readFile } from 'node:fs/promises'

import { ozon } from './fixtures'
import { mockTemplates } from './supply-templates-fixtures'

const output =
  'C:/Users/Artem/Documents/ChatGPT/PERK/outputs/web-supply-templates-20261106'
const file = {
  name: 'original.xlsx',
  mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  buffer: Buffer.from('original-template-test')
}

test('upload an original template, confirm detected columns and download it without changing the plan', async ({
  page
}) => {
  const state = await mockTemplates(page),
    plan = state.plans.seed()
  await page.goto('/supplies')
  await page.getByRole('tab', { name: 'Планы', exact: true }).click()
  await page.getByRole('button', { name: plan.title, exact: true }).click()
  await page
    .getByRole('button', { name: 'Заполнить XLSX', exact: true })
    .click()
  await expect(
    page.getByRole('heading', { name: 'Шаблон поставки', exact: true })
  ).toBeVisible()
  await page.getByLabel('Исходный шаблон XLSX').setInputFiles(file)
  await expect(page.getByLabel('Столбец товара', { exact: true })).toHaveValue(
    'A'
  )
  await expect(
    page.getByLabel('Столбец количества', { exact: true })
  ).toHaveValue('B')
  await expect(
    page.getByRole('region', { name: 'Предпросмотр заполнения' })
  ).toContainText('24 позиций')
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button', { name: 'Скачать XLSX', exact: true }).click()
  ])
  expect(download.suggestedFilename()).toBe('perk-supply-wb.xlsx')
  expect((await readFile((await download.path())!)).toString()).toBe(
    'PK-test-filled-workbook'
  )
  expect(state.fills[0]!.searchParams.get('digest')).toBe('a'.repeat(64))
  expect(state.fills[0]!.searchParams.get('revision')).toBe('1')
  expect(state.csrfValid).toBe(true)
  expect(state.plans.writes).toHaveLength(0)
  const stored = await page.evaluate(() =>
    Object.values(localStorage).join(' ')
  )
  expect(stored).not.toContain('original.xlsx')
  expect(stored).not.toContain('original-template-test')
  await page.screenshot({ path: output + '/template.png', fullPage: true })
  await page.getByRole('button', { name: 'К плану', exact: true }).click()
  await expect(page.getByLabel('К поставке WB-0', { exact: true })).toHaveValue(
    '65'
  )
})

test('manual layout rejects overlapping columns and fills exact selected rows', async ({
  page
}) => {
  const state = await mockTemplates(page),
    plan = state.plans.seed()
  await page.goto('/supplies')
  await page.getByRole('tab', { name: 'Планы', exact: true }).click()
  await page.getByRole('button', { name: plan.title, exact: true }).click()
  await page
    .getByRole('button', { name: 'Заполнить XLSX', exact: true })
    .click()
  await page.getByLabel('Исходный шаблон XLSX').setInputFiles(file)
  await page.getByLabel('Лист шаблона').selectOption('Другой лист')
  await expect(page.getByLabel('Столбец товара', { exact: true })).toHaveValue(
    'D'
  )
  await page.getByLabel('Столбец количества', { exact: true }).selectOption('D')
  await page.getByRole('button', { name: 'Скачать XLSX', exact: true }).click()
  await expect(page.getByRole('dialog')).toContainText(
    'Выберите другой столбец'
  )
  expect(state.fills).toHaveLength(0)
  await page.getByLabel('Столбец количества', { exact: true }).selectOption('G')
  await page.getByLabel('Режим заполнения').selectOption('match')
  await page.getByText('Разметка шаблона', { exact: true }).click()
  await expect(
    page.getByLabel('Первая строка товаров', { exact: true })
  ).toHaveValue('4')
  await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button', { name: 'Скачать XLSX', exact: true }).click()
  ])
  expect(state.fills[0]!.searchParams.get('sheet')).toBe('Другой лист')
  expect(state.fills[0]!.searchParams.get('header_row')).toBe('3')
  expect(state.fills[0]!.searchParams.get('mode')).toBe('match')
})

test('Ozon lets the user select native FBO SKU and keeps that identifier in export', async ({
  page
}) => {
  const state = await mockTemplates(page),
    plan = state.plans.seed(ozon, 'Ozon шаблон')
  await page.goto('/supplies')
  await page.getByRole('combobox', { name: 'Выбрать кабинет' }).click()
  await page
    .getByRole('option', { name: 'PERK Test Ozon · Ozon', exact: true })
    .click()
  await page.getByRole('tab', { name: 'Планы', exact: true }).click()
  await page.getByRole('button', { name: plan.title, exact: true }).click()
  await page
    .getByRole('button', { name: 'Заполнить XLSX', exact: true })
    .click()
  await page.getByLabel('Исходный шаблон XLSX').setInputFiles(file)
  await page
    .getByLabel('Идентификатор товара', { exact: true })
    .selectOption('fbo_sku')
  await expect(
    page.getByRole('region', { name: 'Предпросмотр заполнения' })
  ).toContainText('101')
  await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button', { name: 'Скачать XLSX', exact: true }).click()
  ])
  expect(state.fills[0]!.searchParams.get('identifier_type')).toBe('fbo_sku')
  expect(state.fills[0]!.searchParams.get('data_digest')).toBe('3'.repeat(64))
})

test('file validation happens before upload and server file errors remain readable', async ({
  page
}) => {
  const state = await mockTemplates(page),
    plan = state.plans.seed()
  state.failFill = true
  await page.goto('/supplies')
  await page.getByRole('tab', { name: 'Планы', exact: true }).click()
  await page.getByRole('button', { name: plan.title, exact: true }).click()
  await page
    .getByRole('button', { name: 'Заполнить XLSX', exact: true })
    .click()
  await page
    .getByLabel('Исходный шаблон XLSX')
    .setInputFiles({ ...file, name: 'wrong.xls' })
  await expect(page.getByRole('dialog')).toContainText('Выберите файл XLSX')
  expect(state.inspectCalls).toBe(0)
  await page.getByLabel('Исходный шаблон XLSX').setInputFiles(file)
  await page.getByRole('button', { name: 'Скачать XLSX', exact: true }).click()
  await expect(page.getByRole('dialog')).toContainText('План изменился')
})

test('closing a pending file request releases the page and ignores its late result', async ({
  page
}) => {
  const state = await mockTemplates(page),
    plan = state.plans.seed()
  state.hold = true
  await page.goto('/supplies')
  await page.getByRole('tab', { name: 'Планы', exact: true }).click()
  await page.getByRole('button', { name: plan.title, exact: true }).click()
  await page
    .getByRole('button', { name: 'Заполнить XLSX', exact: true })
    .click()
  await page.getByLabel('Исходный шаблон XLSX').setInputFiles(file)
  await page.getByRole('button', { name: 'Скачать XLSX', exact: true }).click()
  await expect(
    page.getByRole('button', { name: 'Заполняем…', exact: true })
  ).toBeDisabled()
  await page.keyboard.press('Escape')
  await page.getByRole('tab', { name: 'Рекомендации', exact: true }).click()
  state.release?.()
  await expect(page.getByRole('dialog')).toHaveCount(0)
})

test('export rights are required and narrow template controls remain reachable', async ({
  page
}) => {
  const state = await mockTemplates(page),
    plan = state.plans.seed()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/supplies')
  await page.getByRole('tab', { name: 'Планы', exact: true }).click()
  await page.getByRole('button', { name: plan.title, exact: true }).click()
  await page
    .getByRole('button', { name: 'Заполнить XLSX', exact: true })
    .click()
  await page.getByLabel('Исходный шаблон XLSX').setInputFiles(file)
  await expect(
    page.getByRole('button', { name: 'Скачать XLSX', exact: true })
  ).toBeInViewport()
  expect(
    await page
      .getByRole('dialog')
      .evaluate(element => element.scrollWidth <= element.clientWidth)
  ).toBe(true)
  await page.screenshot({
    path: output + '/template-mobile.png',
    fullPage: true
  })
})

test('employees without export rights cannot open template processing', async ({
  page
}) => {
  const state = await mockTemplates(page, 'viewer'),
    plan = state.plans.seed()
  await page.goto('/supplies')
  await page.getByRole('tab', { name: 'Планы', exact: true }).click()
  await page.getByRole('button', { name: plan.title, exact: true }).click()
  await expect(
    page.getByRole('button', { name: 'Заполнить XLSX', exact: true })
  ).toHaveCount(0)
  expect(state.inspectCalls).toBe(0)
})
