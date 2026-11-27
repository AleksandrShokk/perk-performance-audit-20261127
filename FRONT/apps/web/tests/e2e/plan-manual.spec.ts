import { expect, test } from '@playwright/test'

import { mockPlans } from './supply-plans-fixtures'
import { mockTemplates } from './supply-templates-fixtures'

test('remove a product, save an empty plan and delete it without locking the page', async ({
  page
}) => {
  const state = await mockPlans(page)
  const plan = state.seed()
  plan.items = plan.items.slice(0, 1)
  await page.goto('/supplies')
  await page.getByRole('tab', { name: 'Планы', exact: true }).click()
  await page.getByRole('button', { name: plan.title, exact: true }).click()
  await page.getByRole('button', { name: 'Убрать WB-0', exact: true }).click()
  await page
    .getByRole('button', { name: 'Сохранить план', exact: true })
    .click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  expect(state.plans[0]!.items).toHaveLength(0)
  await page.getByRole('button', { name: plan.title, exact: true }).click()
  await page.getByRole('button', { name: 'Удалить план', exact: true }).click()
  await page
    .getByRole('button', { name: 'Удалить навсегда', exact: true })
    .click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  expect(state.plans).toHaveLength(0)
  await page.getByRole('tab', { name: 'Рекомендации', exact: true }).click()
  expect(state.csrfValid).toBe(true)
})

test('dropping an unknown article uploads immediately, keeps one clear error and leaves the plan intact', async ({
  page
}) => {
  const state = await mockPlans(page),
    plan = state.seed()
  await page.goto('/supplies')
  await page.getByRole('tab', { name: 'Планы', exact: true }).click()
  await page.getByRole('button', { name: plan.title, exact: true }).click()
  await page
    .getByRole('button', { name: 'Добавить товары', exact: true })
    .click()
  const count = plan.items.length
  await page.locator('.file-dropzone').evaluate(element => {
    const files = new DataTransfer()
    files.items.add(
      new File(['test-xlsx'], 'unknown.xlsx', {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
      })
    )
    element.dispatchEvent(
      new DragEvent('drop', {
        bubbles: true,
        cancelable: true,
        dataTransfer: files
      })
    )
  })
  await expect(page.getByRole('dialog')).toContainText('товары из файла: 1')
  expect(plan.items).toHaveLength(count)
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.getByRole('tab', { name: 'Рекомендации', exact: true }).click()
})

test('the template form scrolls to its preview at a short window height', async ({
  page
}) => {
  await page.setViewportSize({ width: 1280, height: 700 })
  const state = await mockTemplates(page),
    plan = state.plans.seed()
  await page.goto('/supplies')
  await page.getByRole('tab', { name: 'Планы', exact: true }).click()
  await page.getByRole('button', { name: plan.title, exact: true }).click()
  await page
    .getByRole('button', { name: 'Заполнить XLSX', exact: true })
    .click()
  await page
    .getByLabel('Исходный шаблон XLSX', { exact: true })
    .setInputFiles({
      name: 'original.xlsx',
      mimeType:
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      buffer: Buffer.from('test')
    })
  await page.getByText('Разметка шаблона', { exact: true }).click()
  const scroller = page.locator('.supply-template-content')
  expect(
    await scroller.evaluate(
      element => element.scrollHeight > element.clientHeight
    )
  ).toBe(true)
  await page
    .getByRole('region', { name: 'Предпросмотр заполнения' })
    .scrollIntoViewIfNeeded()
  await expect(
    page.getByRole('region', { name: 'Предпросмотр заполнения' })
  ).toBeInViewport()
  await expect(
    page.getByRole('button', { name: 'Скачать XLSX', exact: true })
  ).toBeInViewport()
  await page.screenshot({
    path: 'C:/Users/Artem/Documents/ChatGPT/PERK/outputs/supply-plans-history-20261108/template-scroll.png'
  })
})
