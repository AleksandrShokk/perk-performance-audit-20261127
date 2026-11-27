import { expect, test } from '@playwright/test'

import { ozon, wb } from './fixtures'
import { mockInventory } from './inventory-fixtures'
import { mockProducts, ozonVariantId } from './products-fixtures'

test('general catalog switches combined cards and edits the selected marketplace variant', async ({
  page
}) => {
  const state = await mockProducts(page)
  const wbModel = state.models[0]!
  const ozonModel = state.models.at(-1)!
  const requests: URL[] = []
  await page.route('**/api/v1/**/product-models*', route => {
    const url = new URL(route.request().url())
    requests.push(url)
    const store = url.searchParams.get('store_id')
    const together =
      !store && url.searchParams.get('combine_marketplaces') === 'true'
    const items = together
      ? [
          {
            ...wbModel,
            id: 'matched:test',
            marketplace: 'combined',
            combined: true,
            grouping: 'matched',
            store_name: 'PERK Test WB · PERK Test Ozon',
            products: [...wbModel.products, ...ozonModel.products]
          }
        ]
      : [wbModel, ozonModel].filter(item => !store || item.store_id === store)
    return route.fulfill({
      json: {
        items,
        total: items.length,
        total_products: items.reduce(
          (sum, item) => sum + item.products.length,
          0
        ),
        total_variants: 5,
        currency: 'RUB',
        limit: 25,
        offset: 0,
        is_loading: false,
        is_partial: false
      }
    })
  })
  await page.goto('/products')
  await expect(
    page.getByRole('combobox', { name: 'Объединение площадок' })
  ).toHaveCount(0)
  await page.getByRole('combobox', { name: 'Выбрать кабинет' }).click()
  await page.getByRole('option', { name: 'Все кабинеты', exact: true }).click()
  await expect(page.locator('.catalog-data tbody tr')).toHaveCount(1)
  await page.locator('.catalog-data tbody tr button').first().click()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('combobox', { name: 'Кабинет товара' }).click()
  await page
    .getByRole('option', { name: 'PERK Test Ozon · Ozon', exact: true })
    .click()
  await expect(dialog.locator('.product-identifiers')).toContainText('BOOT-42')
  await expect(
    dialog.getByRole('button', { name: 'Размер M', exact: true })
  ).toHaveCount(0)
  await dialog.getByRole('button', { name: 'Изменить', exact: true }).click()
  await dialog.getByLabel('Цена, RUB').fill('3650')
  await dialog
    .getByRole('button', { name: 'Сохранить себестоимость', exact: true })
    .click()
  await expect(dialog).toHaveCount(0)
  expect(state.writes[0]!.path).toContain(`/stores/${ozon}/variant-costs`)
  expect(state.writes[0]!.body.variant_id).toBe(ozonVariantId)
  await page.getByRole('combobox', { name: 'Объединение площадок' }).click()
  await page
    .getByRole('option', { name: 'WB и Ozon отдельно', exact: true })
    .click()
  await expect(page.locator('.catalog-data tbody tr')).toHaveCount(2)
  await page.reload()
  await expect(page.locator('.catalog-data tbody tr')).toHaveCount(2)
  expect(requests.at(-1)!.searchParams.get('combine_marketplaces')).toBe(
    'false'
  )
  await page.getByRole('combobox', { name: 'Выбрать кабинет' }).click()
  await page
    .getByRole('option', { name: 'PERK Test WB · WB', exact: true })
    .click()
  await expect(
    page.getByRole('combobox', { name: 'Объединение площадок' })
  ).toHaveCount(0)
  expect(requests.at(-1)!.searchParams.get('store_id')).toBe(wb)
})

test('matching dialog downloads the correction workbook with the original upload and selected cabinets', async ({
  page
}) => {
  await mockProducts(page)
  let correction = ''
  let csrf = ''
  await page.route('**/api/v1/**/catalog/matches**', route => {
    const request = route.request()
    const url = new URL(request.url())
    if (url.pathname.endsWith('/corrections')) {
      correction = request.postData() ?? ''
      csrf = request.headers()['x-csrf-token'] ?? ''
      expect(url.searchParams.get('left_store_id')).toBe(wb)
      expect(url.searchParams.get('right_store_id')).toBe(ozon)
      return route.fulfill({
        contentType:
          'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        body: Buffer.from('workbook-transport-fixture')
      })
    }
    if (url.pathname.endsWith('/preview'))
      return route.fulfill({
        json: {
          can_apply: false,
          preview_id: null,
          valid_count: 1,
          errors: [{ row: 3, message: 'Товар Ozon не найден' }],
          items: []
        }
      })
    return route.fulfill({
      json: { items: [], count: 0, limit: 25, offset: 0 }
    })
  })
  await page.goto('/products')
  await page.getByRole('button', { name: 'WB ↔ Ozon', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.locator('input[type=file]').setInputFiles({
    name: 'matches.xlsx',
    mimeType:
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    buffer: Buffer.from('original-upload-fixture')
  })
  await expect(dialog).toContainText('Товар Ozon не найден')
  const download = page.waitForEvent('download')
  await dialog
    .getByRole('button', { name: 'Скачать файл для исправления', exact: true })
    .click()
  expect((await download).suggestedFilename()).toBe(
    'perk-matches-corrections.xlsx'
  )
  expect(correction).toContain('original-upload-fixture')
  expect(csrf).toBe('pc_test')
})

test('inventory price and identifier controls share a row on wide and narrow screens', async ({
  page
}) => {
  await mockInventory(page)
  await page.goto('/inventory')
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1080 })
    const price = page.getByRole('combobox', { name: 'Оценка остатков' })
    const article = page.getByRole('combobox', { name: 'Отображение артикула' })
    const a = await price.boundingBox(),
      b = await article.boundingBox()
    expect(a && b).toBeTruthy()
    expect(Math.abs(a!.y - b!.y)).toBeLessThan(2)
    expect(a!.x + a!.width).toBeLessThanOrEqual(b!.x)
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth)
    ).toBeLessThanOrEqual(width + 1)
    await page
      .locator('.stock-display-controls')
      .screenshot({
        path: `C:/Users/Artem/Documents/ChatGPT/PERK/outputs/catalog-matches-20261108/inventory-controls-${width}.png`
      })
  }
})
