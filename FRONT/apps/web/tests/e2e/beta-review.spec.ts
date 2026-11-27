import { expect, test } from '@playwright/test'

import { mockApi } from './fixtures'
import { mockProducts } from './products-fixtures'

test('catalog supports a direct page jump and 100 rows without nested short scrolling', async ({
  page
}) => {
  const state = await mockProducts(page)
  const template = state.models[0]!
  const rows = Array.from({ length: 180 }, (_, i) => ({
    ...template,
    id: `test-${i}`,
    title: `Карточка ${i + 1}`
  }))
  const requests: URL[] = []
  await page.route('**/product-models?**', route => {
    const url = new URL(route.request().url())
    requests.push(url)
    const offset = Number(url.searchParams.get('offset') || 0),
      limit = Number(url.searchParams.get('limit') || 25)
    return route.fulfill({
      json: {
        items: rows.slice(offset, offset + limit),
        total: 180,
        total_products: 180,
        total_variants: 180,
        currency: 'RUB',
        limit,
        offset,
        is_loading: false,
        is_partial: false
      }
    })
  })
  await page.goto('/products')
  await expect(page.locator('.catalog-data tbody tr')).toHaveCount(25)
  const nav = page.getByRole('navigation', { name: 'Страницы каталога' })
  await nav
    .getByRole('button', { name: 'Страница 4 каталога', exact: true })
    .click()
  await expect
    .poll(() => requests.at(-1)?.searchParams.get('offset'))
    .toBe('75')
  await nav.getByRole('combobox').click()
  await page
    .getByRole('option', { name: '100 на странице', exact: true })
    .click()
  await expect(page.locator('.catalog-data tbody tr')).toHaveCount(100)
  await expect.poll(() => requests.at(-1)?.searchParams.get('offset')).toBe('0')
})

test('custom calendar has fixed six rows, Russian dates, bounds and selected day count', async ({
  page
}) => {
  await mockApi(page)
  await page.goto('/')
  await page.getByRole('button', { name: 'Свой период', exact: true }).click()
  const dialog = page.getByRole('dialog'),
    grid = dialog.getByRole('group', { name: 'Дни периода' })
  await expect(grid.getByRole('button')).toHaveCount(42)
  await expect(dialog.getByLabel('С', { exact: true })).toHaveValue(
    /\d{2}\.\d{2}\.\d{4}/
  )
  const height = (await grid.boundingBox())!.height
  await dialog.getByRole('button', { name: 'Предыдущий месяц' }).click()
  await expect(grid.getByRole('button')).toHaveCount(42)
  expect((await grid.boundingBox())!.height).toBe(height)
  await dialog.getByLabel('С', { exact: true }).fill('01.09.2026')
  await dialog.getByLabel('По', { exact: true }).fill('30.10.2026')
  await expect(dialog).toContainText('60 дней')
  await dialog.getByRole('button', { name: 'Применить', exact: true }).click()
  await expect(dialog).toHaveCount(0)
})

test('chart tooltip includes prior date, and browser context events are suppressed', async ({
  page
}) => {
  await mockApi(page)
  await page.goto('/')
  await page.locator('.recharts-bar-rectangle').last().hover()
  await expect(page.locator('.chart-tooltip').first()).toContainText(
    'Прошлый период'
  )
  const chart = page.getByRole('group', {
    name: 'Столбчатый график продаж по дням'
  })
  expect(
    await chart.evaluate(element => {
      const event = new MouseEvent('contextmenu', {
        bubbles: true,
        cancelable: true
      })
      element.dispatchEvent(event)
      return event.defaultPrevented
    })
  ).toBe(true)
  await chart.dblclick({ position: { x: 50, y: 50 } })
  await expect(
    page.getByRole('combobox', { name: 'Единицы графика' })
  ).toBeVisible()
})

test('Ozon sizes of one color use size buttons instead of duplicate color cards', async ({
  page
}) => {
  const state = await mockProducts(page)
  const model = state.models.find(m => m.marketplace === 'ozon')!
  const first = model.products[0]!
  model.products.push({
    ...first,
    id: 'ozon-44',
    external_id: '300144',
    vendor_code: 'BOOT-44',
    variants: [
      { ...first.variants[0]!, id: 'size-44', external_id: '44', size: '44' }
    ]
  })
  await page.goto('/products')
  await page.getByRole('combobox', { name: 'Выбрать кабинет' }).click()
  await page
    .getByRole('option', { name: 'PERK Test Ozon · Ozon', exact: true })
    .click()
  await page
    .locator('.catalog-data tbody tr')
    .first()
    .getByRole('button')
    .first()
    .click()
  const dialog = page.getByRole('dialog')
  await expect(
    dialog.getByRole('button', { name: 'Размер 42', exact: true })
  ).toBeVisible()
  await dialog.getByRole('button', { name: 'Размер 44', exact: true }).click()
  await expect(dialog).toContainText('BOOT-44')
  await expect(dialog.locator('.product-color-options button')).toHaveCount(0)
})

test('barcode match preview is reviewable, saves once, and closing restores input', async ({
  page
}) => {
  await mockProducts(page)
  let applied = 0
  await page.route('**/catalog/matches**', route => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/automatic'))
      return route.fulfill({
        json: {
          preview_id: 'preview-1',
          rows_count: 1,
          valid_count: 1,
          errors: [],
          items: [
            {
              row: 1,
              vendor_code: 'GLOVE-BLACK',
              barcode: '001',
              right_vendor_code: 'GLOVE-OZON',
              right_barcode: '001'
            }
          ],
          can_apply: true
        }
      })
    if (path.endsWith('/apply')) {
      applied++
      return route.fulfill({ json: { applied: 1 } })
    }
    return route.fulfill({
      json: { items: [], count: 0, limit: 25, offset: 0 }
    })
  })
  await page.goto('/products')
  await page.getByRole('button', { name: 'WB ↔ Ozon', exact: true }).click()
  await page
    .getByRole('button', { name: 'Подобрать по штрихкодам', exact: true })
    .click()
  await expect(page.getByRole('dialog')).toContainText('GLOVE-OZON')
  expect(applied).toBe(0)
  await page
    .getByRole('dialog')
    .getByRole('button', { name: 'Сохранить', exact: true })
    .click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  expect(applied).toBe(1)
  await page.getByRole('textbox', { name: 'Поиск товаров' }).fill('test')
  await expect(
    page.getByRole('textbox', { name: 'Поиск товаров' })
  ).toHaveValue('test')
})
