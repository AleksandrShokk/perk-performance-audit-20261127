import { expect, test } from '@playwright/test'
import { readFile } from 'node:fs/promises'

import { ozon } from './fixtures'
import { mockPlans } from './supply-plans-fixtures'

const output =
  'C:/Users/Artem/Documents/ChatGPT/PERK/outputs/web-supply-variants-20261106'

test('distribute native sizes, choose a barcode, reopen and export exact variant quantities', async ({
  page
}) => {
  const state = await mockPlans(page),
    plan = state.seed()
  plan.items[0]!.variants = [
    {
      variant_id: 'size-M',
      external_id: '10',
      size: 'M',
      barcodes: ['000101', '000102'],
      barcode: '',
      quantity: 0
    },
    {
      variant_id: 'size-L',
      external_id: '11',
      size: 'L',
      barcodes: ['000103'],
      barcode: '000103',
      quantity: 0
    }
  ]
  await page.goto('/supplies')
  await page.getByRole('tab', { name: 'Планы', exact: true }).click()
  await page.getByRole('button', { name: plan.title, exact: true }).click()
  await expect(
    page.getByRole('button', { name: 'Выгрузить размеры', exact: true })
  ).toBeDisabled()
  await page.getByRole('button', { name: 'Размеры WB-0', exact: true }).click()
  await page.getByLabel('Количество WB-0 · M', { exact: true }).fill('30')
  await page.getByLabel('Количество WB-0 · L', { exact: true }).fill('35')
  await page
    .getByLabel('Штрихкод WB-0 · M', { exact: true })
    .selectOption('000102')
  await expect(page.getByRole('dialog')).toContainText(
    'Распределено 65 из 65 шт.'
  )
  await page
    .getByRole('button', { name: 'Сохранить план', exact: true })
    .click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  expect(state.writes[0]!.items[0]!.variants?.map(row => row.quantity)).toEqual(
    [30, 35]
  )
  await page.getByRole('button', { name: plan.title, exact: true }).click()
  await page.getByRole('button', { name: 'Размеры WB-0', exact: true }).click()
  await expect(
    page.getByLabel('Количество WB-0 · M', { exact: true })
  ).toHaveValue('30')
  await expect(
    page.getByLabel('Штрихкод WB-0 · M', { exact: true })
  ).toHaveValue('000102')
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button', { name: 'Выгрузить размеры', exact: true }).click()
  ])
  const csv = await readFile((await download.path())!, 'utf8')
  expect(csv).toContain('"\'000102";"30"')
  expect(csv).toContain('"\'000103";"35"')
  expect(csv).not.toContain('000101')
  await page.screenshot({ path: output + '/variants.png', fullPage: true })
})

test('a single native Ozon size follows the product quantity and retains barcode choice', async ({
  page
}) => {
  const state = await mockPlans(page),
    plan = state.seed(ozon, 'Размеры Ozon')
  plan.items[0]!.variants![0]!.barcodes.push('000alternate')
  plan.items[0]!.variants![0]!.barcode = ''
  await page.goto('/supplies')
  await page.getByRole('combobox', { name: 'Выбрать кабинет' }).click()
  await page
    .getByRole('option', { name: 'PERK Test Ozon · Ozon', exact: true })
    .click()
  await page.getByRole('tab', { name: 'Планы', exact: true }).click()
  await page.getByRole('button', { name: plan.title, exact: true }).click()
  await page.getByLabel('К поставке OZ-0', { exact: true }).fill('100')
  await page.getByRole('button', { name: 'Размеры OZ-0', exact: true }).click()
  await expect(
    page.getByLabel('Количество OZ-0 · M', { exact: true })
  ).toHaveValue('100')
  await page
    .getByLabel('Штрихкод OZ-0 · M', { exact: true })
    .selectOption('000alternate')
  await page
    .getByRole('button', { name: 'Сохранить план', exact: true })
    .click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  expect(state.writes[0]!.items[0]!.variants?.[0]).toMatchObject({
    quantity: 100,
    barcode: '000alternate'
  })
})

test('legacy plans load sizes explicitly without changing saved quantities', async ({
  page
}) => {
  const state = await mockPlans(page),
    plan = state.seed()
  plan.items.forEach(item => {
    item.variants = []
  })
  await page.goto('/supplies')
  await page.getByRole('tab', { name: 'Планы', exact: true }).click()
  await page.getByRole('button', { name: plan.title, exact: true }).click()
  await page
    .getByRole('button', { name: 'Загрузить размеры', exact: true })
    .click()
  await expect(
    page.getByRole('button', { name: 'Размеры WB-0', exact: true })
  ).toBeVisible()
  await expect(page.getByLabel('К поставке WB-0', { exact: true })).toHaveValue(
    '65'
  )
  await expect(
    page.getByRole('button', { name: 'Загрузить размеры', exact: true })
  ).toHaveCount(0)
  expect(state.csrfValid).toBe(true)
})

test('over-allocation is explained and invalid hidden pages return to the right product', async ({
  page
}) => {
  const state = await mockPlans(page),
    plan = state.seed()
  const item = plan.items[23]!
  item.variants = [
    {
      variant_id: 'one',
      external_id: 'one',
      size: 'M',
      barcodes: ['9991'],
      barcode: '9991',
      quantity: item.quantity
    },
    {
      variant_id: 'two',
      external_id: 'two',
      size: 'L',
      barcodes: ['9992'],
      barcode: '9992',
      quantity: 0
    }
  ]
  await page.goto('/supplies')
  await page.getByRole('tab', { name: 'Планы', exact: true }).click()
  await page.getByRole('button', { name: plan.title, exact: true }).click()
  await page
    .getByRole('dialog')
    .getByRole('button', { name: 'Следующая страница поставок' })
    .click()
  await page.getByRole('button', { name: 'Размеры WB-23', exact: true }).click()
  await page.getByLabel('Количество WB-23 · L', { exact: true }).fill('1')
  await page
    .getByRole('dialog')
    .getByRole('button', { name: 'Предыдущая страница поставок' })
    .click()
  await page
    .getByRole('button', { name: 'Сохранить план', exact: true })
    .click()
  await expect(
    page.getByLabel('К поставке WB-23', { exact: true })
  ).toBeVisible()
  await expect(page.getByRole('dialog')).toContainText(
    'По размерам указано больше'
  )
  expect(state.writes).toHaveLength(0)
})

test('employees can inspect size breakdown but cannot change it', async ({
  page
}) => {
  const state = await mockPlans(page, 'viewer'),
    plan = state.seed()
  await page.goto('/supplies')
  await page.getByRole('tab', { name: 'Планы', exact: true }).click()
  await page.getByRole('button', { name: plan.title, exact: true }).click()
  await page.getByRole('button', { name: 'Размеры WB-0', exact: true }).click()
  await expect(
    page.getByLabel('Количество WB-0 · M', { exact: true })
  ).toBeDisabled()
  await expect(
    page.getByLabel('Штрихкод WB-0 · M', { exact: true })
  ).toBeDisabled()
  await expect(
    page.getByRole('button', { name: 'Выгрузить размеры', exact: true })
  ).toHaveCount(0)
})

test('expanded sizes stay inside the dialog on a narrow screen', async ({
  page
}) => {
  const state = await mockPlans(page),
    plan = state.seed()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/supplies')
  await page.getByRole('tab', { name: 'Планы', exact: true }).click()
  await page.getByRole('button', { name: plan.title, exact: true }).click()
  await page.getByRole('button', { name: 'Размеры WB-0', exact: true }).click()
  await expect(
    page.getByRole('heading', { name: 'План поставки', exact: true })
  ).toBeInViewport()
  await expect(
    page.getByRole('button', { name: 'Сохранить план', exact: true })
  ).toBeInViewport()
  expect(
    await page
      .getByRole('dialog')
      .evaluate(element => element.scrollWidth <= element.clientWidth)
  ).toBe(true)
  await page
    .getByLabel('Количество WB-0 · M', { exact: true })
    .scrollIntoViewIfNeeded()
  await expect(
    page.getByLabel('Количество WB-0 · M', { exact: true })
  ).toBeInViewport()
  await expect(
    page.getByLabel('Штрихкод WB-0 · M', { exact: true })
  ).toBeInViewport()
  await page.screenshot({
    path: output + '/variants-mobile.png',
    fullPage: true
  })
})
