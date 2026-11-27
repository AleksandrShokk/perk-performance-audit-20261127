import { type Page, expect, test } from '@playwright/test'

import { mockProducts, ozonVariantId } from './products-fixtures'

const output =
  'C:/Users/Artem/Documents/ChatGPT/PERK/outputs/web-products-20261106'
const openGloves = (page: Page) =>
  page
    .getByRole('button', {
      name: 'Открыть Мотоперчатки Urban · GLOVE-BLACK',
      exact: true
    })
    .click()

test('catalog uses server pages, search, filters and persistent display preferences', async ({
  page
}) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  const state = await mockProducts(page)
  await page.goto('/products')
  await expect(
    page.getByRole('heading', { name: 'Товары', exact: true })
  ).toBeVisible()
  await expect(page.locator('.catalog-data tbody tr')).toHaveCount(25)
  await page.screenshot({ path: `${output}/catalog-light.png`, fullPage: true })
  await page
    .getByRole('button', { name: 'Следующая страница каталога' })
    .click()
  await expect(page.locator('.catalog-data tbody tr')).toHaveCount(2)
  await page.getByRole('textbox', { name: 'Поиск товаров' }).fill('Модель 20')
  await expect(page.locator('.catalog-data tbody tr')).toHaveCount(1)
  await expect(page.locator('.catalog-data')).toContainText('Модель 20')
  expect(
    state.catalogRequests.some(
      url =>
        new URL(url).searchParams.get('q') === 'Модель 20' &&
        new URL(url).searchParams.get('offset') === '0'
    )
  ).toBe(true)
  await page.getByRole('button', { name: 'Очистить поиск' }).click()
  await expect(page.locator('.catalog-data tbody tr')).toHaveCount(25)
  await page.getByRole('checkbox', { name: 'Все варианты в списке' }).check()
  await expect(page.locator('.catalog-data tbody tr')).toHaveCount(26)
  await page
    .getByRole('combobox', { name: 'Отображение артикула' })
    .selectOption('barcode')
  await expect(page.locator('.catalog-data tbody tr').first()).toContainText(
    '00010101'
  )
  await page.reload()
  await expect(
    page.getByRole('checkbox', { name: 'Все варианты в списке' })
  ).toBeChecked()
  await expect(
    page.getByRole('combobox', { name: 'Отображение артикула' })
  ).toHaveValue('barcode')
  await page
    .getByRole('button', { name: 'Без себестоимости', exact: true })
    .click()
  await expect(page.locator('.catalog-data tbody tr')).toHaveCount(1)
  await expect(page.locator('.catalog-data')).toContainText('Мотошлем Trail')
  await page
    .getByRole('button', { name: 'Без себестоимости', exact: true })
    .click()
  await page.getByRole('button', { name: 'В наличии', exact: true }).click()
  await expect
    .poll(() =>
      state.catalogRequests.some(
        url => new URL(url).searchParams.get('in_stock') === 'true'
      )
    )
    .toBe(true)
  await expect(page.locator('.catalog-table')).toBeVisible()
  await page.getByRole('button', { name: 'Профиль и настройки' }).click()
  await page.getByRole('menuitemradio', { name: 'Тёмная', exact: true }).click()
  await expect(page.locator('html')).toHaveClass(/dark/)
  await page.screenshot({ path: `${output}/catalog-dark.png`, fullPage: true })
  expect(errors).toEqual([])
})

test('card gallery, colors, sizes, warehouse quantities and one-click copying work', async ({
  page,
  context
}) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  await mockProducts(page)
  await page.goto('/products')
  await openGloves(page)
  const dialog = page.getByRole('dialog')
  await expect(dialog.locator('.gallery-position')).toHaveText('1 / 2')
  await dialog.getByRole('button', { name: 'Следующее фото' }).click()
  await expect(dialog.locator('.gallery-position')).toHaveText('2 / 2')
  await dialog.getByRole('button', { name: 'Фото 1', exact: true }).click()
  await expect(dialog.locator('.gallery-position')).toHaveText('1 / 2')
  await dialog
    .getByRole('button', { name: 'Выбрать синий', exact: true })
    .click()
  await expect(dialog.locator('.product-identifiers')).toContainText(
    'GLOVE-BLUE'
  )
  await expect(dialog.locator('.product-gallery-slide img')).toHaveAttribute(
    'src',
    /blue-front/
  )
  await dialog.getByRole('button', { name: 'Размер L', exact: true }).click()
  await expect(dialog.locator('.product-stock-summary')).toContainText('2 шт.')
  await dialog
    .getByRole('button', { name: 'Скопировать штрихкод 00010202', exact: true })
    .click()
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(
    '00010202'
  )
  await dialog.getByText('По складам', { exact: true }).click()
  await expect(dialog).toContainText('Коледино')
  await page.screenshot({ path: `${output}/product-card.png`, fullPage: true })
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await page.getByRole('button', { name: 'Профиль и настройки' }).click()
  await expect(
    page.getByRole('menuitem', { name: 'Выйти из аккаунта' })
  ).toBeVisible()
})

test('WB cost edits use the selected barcode, refresh the catalog and preserve exact history', async ({
  page
}) => {
  const state = await mockProducts(page)
  await page.goto('/products')
  await openGloves(page)
  const dialog = page.getByRole('dialog')
  expect(state.costReads).toHaveLength(0)
  await dialog.getByRole('button', { name: 'Изменить', exact: true }).click()
  await dialog.getByLabel('Цена, RUB').fill('-1')
  await dialog
    .getByRole('button', { name: 'Сохранить себестоимость', exact: true })
    .click()
  await expect(dialog.getByRole('alert')).toContainText('Укажите цену')
  expect(state.writes).toHaveLength(0)
  await dialog.getByLabel('Цена, RUB').fill('1600,5678')
  await dialog.getByLabel('Действует с', { exact: true }).fill('2026-11-01')
  await dialog
    .getByRole('button', { name: 'Сохранить себестоимость', exact: true })
    .click()
  await expect(dialog).toHaveCount(0)
  expect(state.writes[0]!.body).toMatchObject({
    nm_id: '101',
    barcode: '00010101',
    amount: '1600.5678',
    currency: 'RUB',
    effective_from: '2026-11-01'
  })
  expect(state.writes[0]!.path).not.toContain('variant-costs')
  expect(state.csrf).toBe(true)
  await openGloves(page)
  await expect(dialog.locator('.variant-cost-current')).toContainText(
    '1\u00a0600,5678 ₽'
  )
  await dialog.getByText('История себестоимости', { exact: true }).click()
  await expect(
    dialog.locator('.cost-history-list > div').first()
  ).toContainText('1\u00a0600,5678 ₽')
})

test('Ozon keeps native identity and writes cost by variant UUID', async ({
  page
}) => {
  const state = await mockProducts(page)
  await page.goto('/products')
  await page.getByRole('combobox', { name: 'Выбрать кабинет' }).click()
  await page.getByRole('option', { name: 'Все кабинеты', exact: true }).click()
  await expect(page.locator('.catalog-statistics > div').first()).toContainText(
    '28'
  )
  expect(
    state.catalogRequests.some(
      path => !new URL(path).searchParams.has('store_id')
    )
  ).toBe(true)
  await page.getByRole('combobox', { name: 'Выбрать кабинет' }).click()
  await page
    .getByRole('option', { name: 'PERK Test Ozon · Ozon', exact: true })
    .click()
  await page
    .getByRole('combobox', { name: 'Отображение артикула' })
    .selectOption('marketplace')
  await expect(page.locator('.catalog-data')).toContainText('Ozon 900101')
  await page
    .getByRole('button', {
      name: 'Открыть Мотоботы Track · BOOT-42',
      exact: true
    })
    .click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toContainText('PERK Test Ozon · Ozon')
  await dialog.getByRole('button', { name: 'Изменить', exact: true }).click()
  await expect(dialog.getByLabel('Применить к', { exact: true })).toHaveCount(0)
  await dialog.getByLabel('Цена, RUB').fill('3700,25')
  await dialog
    .getByRole('button', { name: 'Сохранить себестоимость', exact: true })
    .click()
  await expect(dialog).toHaveCount(0)
  expect(state.writes[0]!.path).toContain('/variant-costs')
  expect(state.writes[0]!.body.variant_id).toBe(ozonVariantId)
  expect(state.writes[0]!.body).not.toHaveProperty('nm_id')
  await page
    .getByRole('button', { name: 'Импорт себестоимости', exact: true })
    .click()
  await expect(
    dialog.getByRole('button', { name: 'Скачать шаблон XLSX' })
  ).toBeVisible()
  await page.keyboard.press('Escape')
})

test('restricted inventory users have no cost access and the narrow catalog remains readable', async ({
  page
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const state = await mockProducts(page, { permissions: ['inventory.read'] })
  await page.goto('/products')
  await expect(page.locator('.catalog-data tbody tr')).toHaveCount(25)
  await expect(
    page.getByRole('columnheader', { name: 'Себестоимость' })
  ).toHaveCount(0)
  await expect(
    page.getByRole('button', { name: 'Импорт себестоимости', exact: true })
  ).toHaveCount(0)
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth
    )
  ).toBe(true)
  await expect(page.locator('.catalog-stock').first()).toBeInViewport({
    ratio: 0.9
  })
  await page.screenshot({
    path: `${output}/catalog-narrow.png`,
    fullPage: true
  })
  await openGloves(page)
  await expect(page.getByRole('dialog')).not.toContainText('Себестоимость')
  expect(state.costReads).toHaveLength(0)
})

test('profit-only users can open products without receiving stock controls', async ({
  page
}) => {
  await mockProducts(page, { permissions: ['finance.read', 'profit.read'] })
  await page.goto('/products')
  await expect(
    page
      .getByRole('navigation')
      .getByRole('link', { name: 'Товары', exact: true })
  ).toBeVisible()
  await expect(
    page.getByRole('columnheader', { name: 'FBO', exact: true })
  ).toHaveCount(0)
  await expect(
    page.getByRole('button', { name: 'В наличии', exact: true })
  ).toHaveCount(0)
  await openGloves(page)
  await expect(page.locator('.product-stock-summary')).toHaveCount(0)
  await expect(
    page
      .getByRole('dialog')
      .getByRole('button', { name: 'Изменить', exact: true })
  ).toHaveCount(0)
  await expect(page.locator('.variant-cost-current')).toContainText(
    '1\u00a0250,1234 ₽'
  )
})

test('late price save cannot close a newly opened card', async ({ page }) => {
  let release!: () => void
  const gate = new Promise<void>(resolve => {
    release = resolve
  })
  const state = await mockProducts(page, { holdWrite: gate })
  await page.goto('/products')
  await openGloves(page)
  await page
    .getByRole('dialog')
    .getByRole('button', { name: 'Изменить', exact: true })
    .click()
  await page.getByLabel('Цена, RUB').fill('1500')
  const sent = page.waitForRequest(
    req => req.method() !== 'GET' && req.url().endsWith('/costs')
  )
  await page
    .getByRole('button', { name: 'Сохранить себестоимость', exact: true })
    .click()
  await sent
  await page.keyboard.press('Escape')
  await page
    .getByRole('button', {
      name: 'Открыть Мотошлем Trail · ART-201',
      exact: true
    })
    .click()
  const before = state.catalogRequests.length
  release()
  await expect.poll(() => state.catalogRequests.length).toBeGreaterThan(before)
  await expect(
    page
      .getByRole('dialog')
      .getByRole('heading', { name: 'Мотошлем Trail', exact: true })
  ).toBeVisible()
})

test('initial loading turns into cards without remounting the page', async ({
  page
}) => {
  const state = await mockProducts(page, { loading: true })
  await page.goto('/products')
  await expect(
    page.getByText('Загружаем каталог', { exact: true })
  ).toBeVisible()
  await page
    .getByRole('heading', { name: 'Товары', exact: true })
    .evaluate(node => node.setAttribute('data-stable', 'yes'))
  await expect
    .poll(() => state.catalogRequests.length, { timeout: 12000 })
    .toBeGreaterThanOrEqual(2)
  await expect(page.locator('.catalog-data tbody tr')).toHaveCount(25)
  await expect(
    page.getByRole('heading', { name: 'Товары', exact: true })
  ).toHaveAttribute('data-stable', 'yes')
})

test('an empty catalog does not trigger price requests', async ({ page }) => {
  const state = await mockProducts(page, { empty: true })
  await page.goto('/products')
  await expect(
    page.getByText('Товаров пока нет', { exact: true })
  ).toBeVisible()
  expect(state.costReads).toHaveLength(0)
})

test('roles without catalog grants cannot load products', async ({ page }) => {
  const state = await mockProducts(page, { permissions: ['finance.read'] })
  await page.goto('/products')
  await expect(
    page.getByText('Нет доступа к товарам', { exact: true })
  ).toBeVisible()
  expect(state.catalogRequests).toHaveLength(0)
  expect(state.costReads).toHaveLength(0)
})
