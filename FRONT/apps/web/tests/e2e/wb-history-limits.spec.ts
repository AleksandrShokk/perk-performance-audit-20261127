import { lastDays } from '@app/analytics/dates'
import { type Page, expect, test } from '@playwright/test'

import { mockAnalytics } from './analytics-fixtures'
import { ozon, wb } from './fixtures'

const uid = '30000000-0000-4000-8000-000000000001'
const end = lastDays(1).date_to
const original = { date_from: '2025-01-01', date_to: end }

async function setup(page: Page, floor = '2025-11-14') {
  const state = await mockAnalytics(page)
  await page.addInitScript(
    ({ uid, original }) => {
      const filters = JSON.stringify({
        period: original,
        metric: 'orders',
        unit: 'amount',
        comparison: 'none'
      })
      localStorage.setItem(`perk.web.analytics.${uid}`, filters)
      localStorage.setItem(`perk.web.home.${uid}`, filters)
    },
    { uid, original }
  )
  await page.route('**/insights/funnel/availability', route =>
    route.fulfill({ json: { date_from: floor, date_to: end } })
  )
  return state
}

for (const path of ['/analytics', '/']) {
  test(`WB history is bounded and mixed history stays wide on ${path}`, async ({
    page
  }) => {
    const state = await setup(page)
    await page.goto(path)
    const chart = page.getByRole('region', { name: 'Продажи', exact: true })
    await expect(chart.locator('.chart-heading')).toContainText(
      '14 ноября 2025'
    )
    const wbRequests = state.requests.filter(
      url => url.pathname.includes(wb) && url.pathname.endsWith('/funnel')
    )
    expect(wbRequests.length).toBeGreaterThan(0)
    expect(
      wbRequests.every(
        url => url.searchParams.get('date_from')! >= '2025-11-14'
      )
    ).toBe(true)
    await chart.locator('.custom-period').click()
    const dialog = page.getByRole('dialog')
    await dialog.getByRole('combobox', { name: 'Год', exact: true }).click()
    await page.getByRole('option', { name: '2025', exact: true }).click()
    await expect(
      dialog.getByRole('button', { name: '13.11.2025', exact: true })
    ).toBeDisabled()
    await expect(
      dialog.getByRole('button', { name: '14.11.2025', exact: true })
    ).toBeEnabled()
    await expect(
      dialog.getByRole('button', { name: 'Предыдущий месяц', exact: true })
    ).toBeDisabled()
    if (path === '/analytics')
      await dialog.screenshot({
        path: 'C:/Users/Artem/Documents/ChatGPT/PERK/outputs/wb-period-limits-20261108/wb-calendar.png'
      })
    await dialog.getByLabel('С', { exact: true }).fill('01.01.2025')
    await dialog.getByRole('button', { name: 'Применить', exact: true }).click()
    await expect(dialog.getByRole('alert')).toHaveText(
      'История доступна с 14.11.2025'
    )
    await page.keyboard.press('Escape')
    await page.getByRole('combobox', { name: 'Выбрать кабинет' }).click()
    await page
      .getByRole('option', { name: 'Все кабинеты', exact: true })
      .click()
    await expect(chart.locator('.chart-heading')).toContainText('1 января 2025')
    await expect(chart).toContainText('WB учтён с 14.11.2025')
    if (path === '/analytics')
      await chart.screenshot({
        path: 'C:/Users/Artem/Documents/ChatGPT/PERK/outputs/wb-period-limits-20261108/mixed-history.png'
      })
    await chart.locator('.custom-period').click()
    await expect(
      page.getByRole('dialog').getByLabel('С', { exact: true })
    ).toHaveValue('01.01.2025')
    await page.keyboard.press('Escape')
    await page.getByRole('combobox', { name: 'Выбрать кабинет' }).click()
    await page
      .getByRole('option', { name: 'PERK Test Ozon · Ozon', exact: true })
      .click()
    await expect(chart.locator('.chart-heading')).toContainText('1 января 2025')
    await expect(chart).not.toContainText('WB учтён')
    await expect
      .poll(() =>
        state.requests.some(
          url =>
            url.pathname.includes(ozon) &&
            url.searchParams.get('date_from') === '2025-01-01'
        )
      )
      .toBe(true)
  })
}

test('archived WB history remains selectable and finance keeps its original calendar', async ({
  page
}) => {
  await setup(page, '2024-06-01')
  await page.goto('/analytics')
  await expect(page.locator('.chart-heading')).toContainText('1 января 2025')
  await page.locator('.custom-period').click()
  await page
    .getByRole('dialog')
    .getByRole('combobox', { name: 'Год', exact: true })
    .click()
  await expect(
    page.getByRole('option', { name: '2024', exact: true })
  ).toBeVisible()
  await page.keyboard.press('Escape')
  await page.keyboard.press('Escape')
  await page.goto('/finance')
  await page.getByRole('button', { name: 'Свой период', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('combobox', { name: 'Год', exact: true }).click()
  await expect(
    page.getByRole('option', { name: '2024', exact: true })
  ).toBeVisible()
})
