import { expect, test } from '@playwright/test'

import { mockApi } from './fixtures'

test('desktop uses a wide chart, right column, clickable metrics and real table tabs', async ({
  page
}) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await mockApi(page)
  await page.goto('/')
  const chart = page.locator('#sales')
  const attention = page.locator('.attention-panel')
  await expect(chart).toBeVisible()
  await expect(attention).toBeVisible()
  const chartBox = await chart.boundingBox()
  const attentionBox = await attention.boundingBox()
  expect(attentionBox!.x).toBeGreaterThan(chartBox!.x + chartBox!.width)
  expect(Math.abs(attentionBox!.y - chartBox!.y)).toBeLessThan(2)
  await page.getByRole('button', { name: /^Выкуплено/ }).click()
  await expect(
    page.getByRole('button', { name: /^Выкуплено/ })
  ).toHaveAttribute('aria-pressed', 'true')
  await page.getByRole('button', { name: /^Отмены и возвраты/ }).click()
  await expect(
    page.getByRole('button', { name: /^Отмены и возвраты/ })
  ).toHaveAttribute('aria-pressed', 'true')
  await expect(page.locator('#reports')).toContainText('Мотошлем Trail')
  await page.getByRole('button', { name: /Заканчиваются/ }).click()
  await expect(
    page.getByRole('tab', { name: 'Поставки', exact: true })
  ).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByRole('tabpanel')).toContainText('К поставке')
  await page.getByRole('button', { name: 'В работе', exact: true }).click()
  await expect(page.getByRole('tabpanel')).toContainText('SUP-101')
  await expect(page.getByRole('tabpanel')).toContainText('Готова к отгрузке')
  await page.getByRole('tab', { name: 'Остатки', exact: true }).click()
  await expect(page.getByRole('tabpanel')).toContainText('По себестоимости')
  await page.keyboard.press('ArrowLeft')
  await expect(
    page.getByRole('tab', { name: 'Топ товаров', exact: true })
  ).toHaveAttribute('aria-selected', 'true')
  expect(errors).toEqual([])
})

test('all sections have working navigation and unfinished sections keep their templates', async ({
  page
}) => {
  await mockApi(page)
  await page.goto('/')
  for (const [path, title] of [
    ['analytics', 'Аналитика'],
    ['products', 'Товары'],
    ['finance', 'Финансы'],
    ['inventory', 'Остатки'],
    ['supplies', 'Поставки']
  ]) {
    await page
      .getByRole('navigation', { name: 'Разделы' })
      .getByRole('link', { name: title, exact: true })
      .click()
    await expect(page).toHaveURL(new RegExp(`/${path}$`))
    await expect(
      page.getByRole('heading', { name: title, exact: true, level: 1 })
    ).toBeVisible()
    await expect(
      page
        .getByRole('navigation')
        .getByRole('link', { name: title, exact: true })
    ).toHaveAttribute('aria-current', 'page')
    if (path === 'analytics')
      await expect(
        page.getByRole('region', { name: 'Воронка продаж' })
      ).toBeVisible()
    else if (path === 'finance')
      await expect(
        page.getByRole('heading', { name: 'Доходы и расходы', exact: true })
      ).toBeVisible()
    else if (path === 'products')
      await expect(
        page.getByRole('region', { name: 'Каталог товаров' })
      ).toBeVisible()
    else if (path === 'inventory')
      await expect(
        page.getByRole('region', { name: 'Остатки по товарам' })
      ).toBeVisible()
    else if (path === 'supplies')
      await expect(
        page.getByRole('region', { name: 'Рекомендации к поставке' })
      ).toBeVisible()
    else await expect(page.getByText('Шаблон', { exact: true })).toBeVisible()
  }
  await page.screenshot({
    path: 'C:/Users/Artem/Documents/ChatGPT/PERK/outputs/web-desktop-20261105/section-template.png',
    fullPage: true
  })
  await page
    .getByRole('navigation', { name: 'Разделы' })
    .getByRole('link', { name: 'Главная', exact: true })
    .click()
  await expect(
    page.getByRole('heading', { name: 'Обзор', exact: true })
  ).toBeVisible()
})

test('a restricted role cannot open a finance template and anonymous visitors go to login', async ({
  page
}) => {
  const state = await mockApi(page, { role: 'viewer' })
  await page.goto('/finance')
  await expect(page.getByText('Нет доступа к разделу')).toBeVisible()
  await expect(
    page
      .getByRole('navigation')
      .getByRole('link', { name: 'Финансы', exact: true })
  ).toHaveCount(0)
  expect(state.reportCalls).toBe(0)
  state.signedIn = false
  await page.context().clearCookies()
  await page.reload()
  await expect(page).toHaveURL(/\/login$/)
})
