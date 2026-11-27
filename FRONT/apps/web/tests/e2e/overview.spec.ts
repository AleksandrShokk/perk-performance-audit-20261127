import { expect, test } from '@playwright/test'

import { mockApi } from './fixtures'

const screenshots =
  'C:/Users/Artem/Documents/ChatGPT/PERK/outputs/web-desktop-20261105'

test('dashboard loads WB, changes store, persists period, opens reports and signs out', async ({
  page
}) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  const state = await mockApi(page)
  await page.goto('/')
  await expect(
    page.getByRole('heading', { name: 'Обзор', exact: true })
  ).toBeVisible()
  await expect(page.locator('#finance')).toContainText(/100\s000/)
  await expect(
    page.getByRole('tab', { name: 'Топ товаров', exact: true })
  ).toBeVisible()
  await page.screenshot({
    path: `${screenshots}/desktop-light.png`,
    fullPage: true
  })
  await page.getByRole('button', { name: '14 дней', exact: true }).click()
  await expect(
    page.getByRole('button', { name: '14 дней', exact: true })
  ).toHaveAttribute('aria-pressed', 'true')
  await page.reload()
  await expect(
    page.getByRole('button', { name: '14 дней', exact: true })
  ).toHaveAttribute('aria-pressed', 'true')
  await page.getByRole('combobox', { name: 'Выбрать кабинет' }).click()
  await page.getByRole('option', { name: 'Все кабинеты', exact: true }).click()
  await expect(page.locator('#finance')).toContainText(/300\s000/)
  await page.getByRole('combobox', { name: 'Выбрать кабинет' }).click()
  await page
    .getByRole('option', { name: 'PERK Test Ozon · Ozon', exact: true })
    .click()
  await expect(page.locator('#finance')).toContainText(/200\s000/)
  await page
    .getByRole('button', { name: 'Финансовый отчёт', exact: true })
    .click()
  await expect(page.getByRole('dialog')).toContainText('Комиссия и эквайринг')
  await page
    .getByRole('dialog')
    .getByRole('button', { name: 'Закрыть', exact: true })
    .click()
  await page.getByRole('tab', { name: 'Остатки', exact: true }).click()
  await expect(page.locator('#reports')).toContainText('Мотошлем Trail')
  await page.getByRole('button', { name: 'Профиль и настройки' }).click()
  await page.getByRole('menuitemradio', { name: 'Тёмная', exact: true }).click()
  await expect(page.locator('html')).toHaveClass(/dark/)
  await page.screenshot({
    path: `${screenshots}/desktop-dark.png`,
    fullPage: true
  })
  await page.getByRole('button', { name: 'Профиль и настройки' }).click()
  await page.getByRole('menuitem', { name: 'Выйти из аккаунта' }).click()
  await expect(page).toHaveURL(/\/login$/)
  await expect(
    page.getByRole('heading', { name: 'Рады видеть вас' })
  ).toBeVisible()
  expect(state.logoutCalls).toBe(1)
  expect(state.csrfValid).toBe(true)
  expect(errors).toEqual([])
})

test('login requires MFA, shows invalid code and does not persist credentials', async ({
  page
}) => {
  const state = await mockApi(page, { signedIn: false })
  await page.goto('/login')
  await page.getByLabel('Email или телефон').fill('web-test@perk.local')
  await page
    .getByLabel('Пароль', { exact: true })
    .fill('test-password-only-123')
  await page.getByRole('button', { name: 'Войти', exact: true }).click()
  await expect(page).toHaveURL(/\/verify$/)
  await page.getByLabel('Код подтверждения', { exact: true }).fill('000000')
  await page.getByRole('button', { name: 'Подтвердить', exact: true }).click()
  await expect(page.locator('.error-notice')).toContainText('Неверный код')
  await page.getByLabel('Код подтверждения', { exact: true }).fill('123456')
  await page.getByRole('button', { name: 'Подтвердить', exact: true }).click()
  await expect(
    page.getByRole('heading', { name: 'Обзор', exact: true })
  ).toBeVisible()
  expect(state.loginCalls).toBe(1)
  expect(state.verifyCalls).toBe(2)
  expect(state.csrfValid).toBe(true)
  const values = await page.evaluate(() =>
    Object.values(localStorage).join(' ')
  )
  expect(values).not.toContain('test-password-only-123')
  expect(values).not.toContain('pc_test')
})

test('registration and password recovery have real routes and validation', async ({
  page
}) => {
  await mockApi(page, { signedIn: false })
  await page.goto('/login')
  await page.getByRole('button', { name: 'Создать', exact: true }).click()
  await expect(page).toHaveURL(/\/register$/)
  await page.getByLabel('Название компании').fill('Test company')
  await page.getByLabel('Email', { exact: true }).fill('test@perk.local')
  await page.getByLabel('Пароль · от 15 символов').fill('short')
  await page.getByRole('button', { name: 'Продолжить', exact: true }).click()
  await expect(page.locator('.field-error')).toBeVisible()
  await page.getByRole('button', { name: 'Ко входу' }).click()
  await page.getByRole('button', { name: 'Забыли пароль?' }).click()
  await expect(page).toHaveURL(/\/forgot-password$/)
  await page.getByLabel('Email', { exact: true }).fill('test@perk.local')
  await page.getByRole('button', { name: 'Получить код', exact: true }).click()
  await page
    .getByLabel('Новый пароль · от 15 символов')
    .fill('new-test-password-123')
  await page.getByLabel('Код подтверждения', { exact: true }).fill('123456')
  await page.getByRole('button', { name: 'Подтвердить', exact: true }).click()
  await expect(
    page.getByRole('heading', { name: 'Пароль изменён' })
  ).toBeVisible()
})

test('mobile viewport fits, dialogs close and restricted roles only load permitted reports', async ({
  page
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mockApi(page, { role: 'viewer' })
  await page.goto('/')
  await expect(
    page.getByRole('heading', { name: 'Обзор', exact: true })
  ).toBeVisible()
  await expect(page.locator('#inventory')).toBeVisible()
  await expect(page.locator('#finance')).toHaveCount(0)
  await expect(page.locator('#sales')).toHaveCount(0)
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth
    )
  ).toBe(true)
  await page.screenshot({ path: `${screenshots}/mobile.png`, fullPage: true })
  await expect(
    page.getByRole('tab', { name: 'Остатки', exact: true })
  ).toHaveAttribute('aria-selected', 'true')
  await expect(page.locator('#reports')).toContainText('Мотошлем Trail')
  await page.getByRole('button', { name: 'Профиль и настройки' }).click()
  await expect(
    page.getByRole('menuitem', { name: 'Выйти из аккаунта' })
  ).toBeVisible()
})

test('custom period rejects reversed dates without issuing report requests', async ({
  page
}) => {
  const state = await mockApi(page)
  await page.goto('/')
  await page.getByRole('button', { name: 'Свой период', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('С', { exact: true }).fill('2026-10-20')
  await dialog.getByLabel('По', { exact: true }).fill('2026-10-01')
  const count = state.reportCalls
  await dialog.getByRole('button', { name: 'Применить', exact: true }).click()
  await expect(dialog.getByRole('alert')).toContainText(
    'Начало периода позже окончания'
  )
  expect(state.reportCalls).toBe(count)
})

test('registration continues through email, phone and copying all recovery codes', async ({
  page
}) => {
  await mockApi(page, { signedIn: false })
  await page.goto('/register')
  await page.getByLabel('Название компании').fill('PERK Test company')
  await page
    .getByLabel('Email', { exact: true })
    .fill('new-web-test@perk.local')
  await page.getByLabel('Пароль · от 15 символов').fill('new-test-password-123')
  await page.getByRole('button', { name: 'Продолжить', exact: true }).click()
  await page.getByLabel('Код подтверждения', { exact: true }).fill('123456')
  await page.getByRole('button', { name: 'Подтвердить', exact: true }).click()
  await expect(page).toHaveURL(/\/phone$/)
  await page.getByLabel('Номер телефона').fill('+79990000001')
  await page.getByRole('button', { name: 'Получить код', exact: true }).click()
  await page.getByLabel('Код подтверждения', { exact: true }).fill('123456')
  await page.getByRole('button', { name: 'Подтвердить', exact: true }).click()
  await expect(
    page.getByRole('heading', { name: 'Сохраните резервные коды' })
  ).toBeVisible()
  await page.evaluate(() => {
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: {
        writeText: async (value: string) => {
          document.body.dataset.copied = value
        }
      }
    })
  })
  await page
    .getByRole('button', { name: 'Скопировать все коды', exact: true })
    .click()
  const copied = await page.locator('body').getAttribute('data-copied')
  expect(copied?.split('\n')).toHaveLength(2)
  await page.getByRole('button', { name: 'Продолжить', exact: true }).click()
  await expect(
    page.getByRole('heading', { name: 'Обзор', exact: true })
  ).toBeVisible()
})

test('switching accounts from MFA returns to a working login page', async ({
  page
}) => {
  const state = await mockApi(page, { mfa: false })
  await page.goto('/verify')
  await page
    .getByRole('button', { name: 'Войти в другой аккаунт', exact: true })
    .click()
  await expect(page).toHaveURL(/\/login$/)
  await expect(
    page.getByRole('heading', { name: 'Рады видеть вас' })
  ).toBeVisible()
  expect(state.logoutCalls).toBe(1)
})

test('chart tooltip retains both money and quantities in quantity mode', async ({
  page
}) => {
  await mockApi(page)
  await page.goto('/')
  await page.getByRole('combobox', { name: 'Единицы графика' }).click()
  await page
    .getByRole('option', { name: 'Количество, шт.', exact: true })
    .click()
  const bar = page.locator('.recharts-bar-rectangle').last()
  await bar.hover()
  const tooltip = page.locator('.chart-tooltip').first()
  await expect(tooltip).toContainText(/5\sшт/)
  await expect(tooltip).toContainText(/5\s000\s₽/)
})
