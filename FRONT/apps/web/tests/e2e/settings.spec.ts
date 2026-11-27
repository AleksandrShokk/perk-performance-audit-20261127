import { expect, test } from '@playwright/test'

import { ozon, wb } from './fixtures'
import { employeeId, inviteCode, settingsApi } from './settings-fixtures'

test('settings navigation, expired cabinets and safe rename', async ({
  page
}) => {
  const state = await settingsApi(page)
  await page.goto('/settings')
  await expect(
    page.getByRole('cell', { name: 'Токен истёк', exact: true })
  ).toBeVisible()
  await page.getByRole('button', { name: 'Настроить PERK Test WB' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Название кабинета').fill('   ')
  await dialog.getByRole('button', { name: 'Сохранить название' }).click()
  await expect(
    dialog.getByText('Введите название', { exact: true })
  ).toBeVisible()
  expect(state.writes).toHaveLength(0)
  await dialog.getByLabel('Название кабинета').fill('Новый WB')
  await dialog.getByRole('button', { name: 'Сохранить название' }).click()
  await expect(dialog.getByText('Название сохранено')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(
    page.getByRole('button', { name: 'Настроить Новый WB' })
  ).toBeVisible()
  expect(state.stores[0]!.id).toBe(wb)
  expect(state.auth.csrfValid).toBe(true)
  await page.screenshot({
    path: 'C:/Users/Artem/Documents/ChatGPT/PERK/outputs/web-settings-20261106/stores.png',
    fullPage: true
  })
})

test('WB token replacement confirms once, keeps identity and clears secret', async ({
  page
}) => {
  const state = await settingsApi(page)
  state.stepUp = false
  await page.goto('/settings')
  await page.getByRole('button', { name: 'Настроить PERK Test WB' }).click()
  await page
    .getByLabel('Новый API-токен')
    .fill('synthetic-test-token-1234567890')
  await page.getByRole('button', { name: 'Сохранить ключ' }).click()
  const confirm = page.getByRole('dialog', { name: 'Подтвердите действие' })
  await expect(confirm).toBeVisible()
  expect(state.sendCalls).toBe(0)
  await confirm.getByRole('button', { name: 'Получить код' }).click()
  await confirm.getByLabel('Код подтверждения').fill('123456')
  await confirm
    .getByRole('button', { name: 'Подтвердить', exact: true })
    .click()
  await expect(page.getByText('Ключ обновлён')).toBeVisible()
  await expect(page.getByLabel('Новый API-токен')).toHaveValue('')
  expect(state.sendCalls).toBe(1)
  expect(state.verifyCalls).toBe(1)
  expect(state.writes).toEqual([
    {
      path: expect.stringContaining(`${wb}/credential`),
      body: { token: 'synthetic-test-token-1234567890' }
    }
  ])
  expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toContain(
    'synthetic-test-token'
  )
  expect(state.auth.csrfValid).toBe(true)
})

test('cancel confirmation then reopen another cabinet without blocked controls', async ({
  page
}) => {
  const state = await settingsApi(page)
  state.stepUp = false
  await page.goto('/settings')
  await page.getByRole('button', { name: 'Настроить PERK Test WB' }).click()
  await page
    .getByLabel('Новый API-токен')
    .fill('synthetic-test-token-1234567890')
  await page.getByRole('button', { name: 'Сохранить ключ' }).click()
  await page
    .getByRole('dialog', { name: 'Подтвердите действие' })
    .getByRole('button', { name: 'Отмена', exact: true })
    .click()
  await expect(
    page.getByRole('button', { name: 'Сохранить ключ' })
  ).toBeEnabled()
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: 'Настроить PERK Test Ozon' }).click()
  await expect(page.getByLabel('Новый API Key')).toBeEditable()
  expect(state.writes).toHaveLength(0)
})

test('Ozon key replacement uses existing Client ID and reports mismatched seller', async ({
  page
}) => {
  const state = await settingsApi(page)
  await page.goto('/settings')
  await page.getByRole('button', { name: 'Настроить PERK Test Ozon' }).click()
  await expect(
    page.getByRole('dialog').getByText('123456', { exact: true })
  ).toBeVisible()
  await page.getByLabel('Новый API Key').fill('WRONG-SELLER-KEY')
  await page.getByRole('button', { name: 'Сохранить ключ' }).click()
  await expect(page.locator('.error-notice')).toContainText(
    'Ключ принадлежит другому продавцу'
  )
  await page.getByLabel('Новый API Key').fill('synthetic-new-ozon-key')
  await page.getByRole('button', { name: 'Сохранить ключ' }).click()
  await expect(page.getByText('Ключ обновлён')).toBeVisible()
  expect(state.writes[0]).toEqual({
    path: expect.stringContaining(`${ozon}/ozon-credential`),
    body: { client_id: '123456', api_key: 'synthetic-new-ozon-key' }
  })
})

test('connection check refreshes status', async ({ page }) => {
  const state = await settingsApi(page)
  await page.goto('/settings')
  await page.getByRole('button', { name: 'Настроить PERK Test WB' }).click()
  await page
    .getByRole('button', { name: 'Проверить подключение', exact: true })
    .click()
  await expect(page.getByText('Подключение проверено')).toBeVisible()
  await expect(
    page.getByRole('dialog').getByText('Подключён', { exact: true })
  ).toBeVisible()
  expect(state.checks).toBe(1)
})

test('team invitation supports selected cabinets, permission dependencies and admin', async ({
  page
}) => {
  const state = await settingsApi(page)
  await page.goto('/settings/team')
  await expect(
    page.getByRole('button', { name: 'Изменить доступ web-test@perk.local' })
  ).toHaveCount(0)
  await page
    .getByRole('button', { name: 'Пригласить сотрудника', exact: true })
    .click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Email сотрудника').fill('new@perk.local')
  await dialog.getByLabel('Все кабинеты, включая новые').uncheck()
  await dialog.getByLabel('PERK Test Ozon', { exact: true }).check()
  await dialog.getByLabel('Изменение себестоимости', { exact: true }).check()
  await expect(dialog.getByLabel('Финансы', { exact: true })).toBeChecked()
  await expect(
    dialog.getByLabel('Себестоимость и прибыль', { exact: true })
  ).toBeChecked()
  await dialog.getByRole('button', { name: 'Отправить приглашение' }).click()
  await expect(
    page.getByText('Приглашение отправлено', { exact: true })
  ).toBeVisible()
  expect(state.writes[0]!.body).toMatchObject({
    email: 'new@perk.local',
    store_ids: [ozon],
    permissions: expect.arrayContaining([
      'costs.write',
      'profit.read',
      'finance.read'
    ])
  })
  await page
    .getByRole('button', { name: 'Пригласить сотрудника', exact: true })
    .click()
  await page.getByLabel('Роль сотрудника').selectOption('admin')
  await expect(
    page.getByRole('dialog').getByText('Все функции и кабинеты')
  ).toBeVisible()
  await expect(page.getByRole('dialog').getByRole('checkbox')).toHaveCount(0)
  await page.keyboard.press('Escape')
  await page.screenshot({
    path: 'C:/Users/Artem/Documents/ChatGPT/PERK/outputs/web-settings-20261106/team.png',
    fullPage: true
  })
})

test('member access can be changed and removed with confirmation', async ({
  page
}) => {
  const state = await settingsApi(page)
  await page.goto('/settings/team')
  await page
    .getByRole('button', { name: 'Изменить доступ employee@perk.local' })
    .click()
  await page.getByLabel('Роль сотрудника').selectOption('accountant')
  await page
    .getByRole('button', { name: 'Сохранить доступ', exact: true })
    .click()
  await expect(page.getByText('Права сохранены')).toBeVisible()
  expect(state.members.find(m => m.user_id === employeeId)!.role).toBe(
    'accountant'
  )
  await page
    .getByRole('button', { name: 'Изменить доступ employee@perk.local' })
    .click()
  await page
    .getByRole('button', { name: 'Удалить сотрудника', exact: true })
    .click()
  await expect(
    page.getByRole('dialog', { name: 'Удалить сотрудника?' })
  ).toBeVisible()
  await page
    .getByRole('button', { name: 'Удалить сотрудника', exact: true })
    .click()
  await expect(
    page.getByText('Сотрудник удалён', { exact: true })
  ).toBeVisible()
  expect(state.members).toHaveLength(1)
})

test('mail failure leaves invitation visible for resend and cancellation', async ({
  page
}) => {
  const state = await settingsApi(page)
  state.inviteFails = true
  await page.goto('/settings/team')
  await page
    .getByRole('button', { name: 'Пригласить сотрудника', exact: true })
    .click()
  await page.getByLabel('Email сотрудника').fill('mail@perk.local')
  await page.getByRole('button', { name: 'Отправить приглашение' }).click()
  await expect(page.locator('.error-notice')).toContainText(
    'Не удалось отправить письмо'
  )
  await page.keyboard.press('Escape')
  await page
    .getByRole('button', { name: 'Отправить снова mail@perk.local' })
    .click()
  await page
    .getByRole('dialog')
    .getByRole('button', { name: 'Отправить', exact: true })
    .click()
  await expect(
    page.getByText('Приглашение отправлено', { exact: true })
  ).toBeVisible()
  await page
    .getByRole('button', { name: 'Отменить приглашение mail@perk.local' })
    .click()
  await page
    .getByRole('dialog')
    .getByRole('button', { name: 'Отменить приглашение', exact: true })
    .click()
  await expect(page.getByText('Ожидающих приглашений нет')).toBeVisible()
})

test('closing an invitation in flight never closes or freezes a new editor', async ({
  page
}) => {
  const state = await settingsApi(page)
  state.inviteDelay = 2000
  await page.goto('/settings/team')
  await page
    .getByRole('button', { name: 'Пригласить сотрудника', exact: true })
    .click()
  await page.getByLabel('Email сотрудника').fill('late@perk.local')
  await page.getByRole('button', { name: 'Отправить приглашение' }).click()
  await expect.poll(() => state.writes.length).toBe(1)
  await page.keyboard.press('Escape')
  await page
    .getByRole('button', { name: 'Пригласить сотрудника', exact: true })
    .click()
  await page.getByLabel('Email сотрудника').fill('fresh@perk.local')
  await expect(page.getByLabel('Email сотрудника')).toHaveValue(
    'fresh@perk.local'
  )
  await expect(
    page.locator('button[aria-label="Отправить снова late@perk.local"]')
  ).toBeAttached()
  await expect(page.getByLabel('Email сотрудника')).toBeEditable()
})

test('restricted employee has own profile but no company settings or team requests', async ({
  page
}) => {
  const state = await settingsApi(page, { role: 'viewer' })
  await page.goto('/settings/team')
  await expect(
    page.getByText('Нет доступа к настройкам компании')
  ).toBeVisible()
  expect(state.teamCalls).toBe(0)
  await page
    .getByRole('navigation', { name: 'Настройки', exact: true })
    .getByRole('link', { name: 'Профиль' })
    .click()
  await expect(page.getByLabel('Текущий пароль')).toBeVisible()
  await expect(
    page
      .getByRole('navigation', { name: 'Настройки', exact: true })
      .getByRole('link', { name: 'Команда' })
  ).toHaveCount(0)
})

test('password validation, error and successful change end the session', async ({
  page
}) => {
  const state = await settingsApi(page)
  await page.goto('/settings/profile')
  await expect(page.getByLabel('Текущий пароль')).toBeVisible()
  await page.getByLabel('Текущий пароль').fill('incorrect-password')
  await page.getByLabel('Новый пароль · от 15 символов').fill('short')
  await page
    .getByRole('button', { name: 'Сменить пароль', exact: true })
    .click()
  expect(state.writes).toHaveLength(0)
  await page
    .getByLabel('Новый пароль · от 15 символов')
    .fill('a-new-strong-password-123')
  await page
    .getByRole('button', { name: 'Сменить пароль', exact: true })
    .click()
  await expect(page.locator('.error-notice')).toContainText(
    'Неверный текущий пароль'
  )
  await page.getByLabel('Текущий пароль').fill('correct-current-password')
  await page
    .getByRole('button', { name: 'Сменить пароль', exact: true })
    .click()
  await expect(page).toHaveURL(/\/login$/)
  expect(state.auth.signedIn).toBe(false)
  expect(await page.evaluate(() => document.cookie)).not.toContain('perk_csrf')
  expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toContain(
    'password-123'
  )
})

test('logout all devices requires confirmation and returns to login', async ({
  page
}) => {
  const state = await settingsApi(page)
  await page.goto('/settings/profile')
  await expect(page.getByLabel('Текущий пароль')).toBeVisible()
  await page.screenshot({
    path: 'C:/Users/Artem/Documents/ChatGPT/PERK/outputs/web-settings-20261106/profile.png',
    fullPage: true
  })
  await page
    .getByRole('button', { name: 'Выйти на всех устройствах', exact: true })
    .click()
  expect(state.auth.signedIn).toBe(true)
  await page.getByRole('button', { name: 'Завершить все сессии' }).click()
  await expect(page).toHaveURL(/\/login$/)
  expect(state.writes[0]!.path).toContain('/auth/logout-all')
  await page.goto('/settings/profile')
  await expect(page).toHaveURL(/\/login$/)
})

test('invitation registration keeps the link through email and phone verification', async ({
  page
}) => {
  const state = await settingsApi(page, { signedIn: false, invited: true })
  await page.goto(`/invite#code=${inviteCode}`)
  await expect(page).toHaveURL(/\/invite$/)
  await expect(
    page.getByText('employee@perk.local', { exact: true })
  ).toBeVisible()
  await page
    .getByRole('link', { name: 'Зарегистрироваться', exact: true })
    .click()
  await expect(page.getByLabel('Email', { exact: true })).toHaveValue(
    'employee@perk.local'
  )
  await expect(page.getByLabel('Название компании')).toHaveCount(0)
  await page
    .getByLabel('Пароль · от 15 символов')
    .fill('synthetic-new-account-password-123')
  await page.getByRole('button', { name: 'Продолжить', exact: true }).click()
  await expect(
    page.getByRole('heading', { name: 'Проверьте почту' })
  ).toBeVisible()
  expect(state.registered).toMatchObject({
    email: 'employee@perk.local',
    invite_code: inviteCode
  })
  await page.getByLabel('Код подтверждения').fill('123456')
  await page.getByRole('button', { name: 'Подтвердить', exact: true }).click()
  await expect(page).toHaveURL(/\/phone$/)
  await page.getByLabel('Номер телефона').fill('+79001234567')
  await page.getByRole('button', { name: 'Получить код', exact: true }).click()
  await page.getByLabel('Код подтверждения').fill('123456')
  await page.getByRole('button', { name: 'Подтвердить', exact: true }).click()
  await expect(
    page.getByRole('heading', { name: 'Сохраните резервные коды' })
  ).toBeVisible()
  await page.getByRole('button', { name: 'Продолжить', exact: true }).click()
  await expect(page).toHaveURL(/\/invite$/)
  await page
    .getByRole('button', { name: 'Присоединиться', exact: true })
    .click()
  await expect(page).toHaveURL('http://localhost:3000/')
  expect(state.accepted).toBe(true)
  expect(
    await page.evaluate(() => sessionStorage.getItem('perk.web.pending-invite'))
  ).toBeNull()
  expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toContain(
    inviteCode
  )
  expect(state.auth.csrfValid).toBe(true)
})

test('wrong account can sign out without losing invitation', async ({
  page
}) => {
  const state = await settingsApi(page)
  await page.goto(`/invite#code=${inviteCode}`)
  await page.getByRole('button', { name: 'Войти в другой аккаунт' }).click()
  await expect(page).toHaveURL(/\/login$/)
  await expect(page.getByLabel('Email или телефон')).toHaveValue(
    'employee@perk.local'
  )
  expect(state.auth.signedIn).toBe(false)
  expect(
    await page.evaluate(() => sessionStorage.getItem('perk.web.pending-invite'))
  ).toContain(inviteCode)
})

test('expired and malformed invitations have a working exit', async ({
  page
}) => {
  const state = await settingsApi(page, { signedIn: false })
  state.expired = true
  await page.goto(`/invite#code=${inviteCode}`)
  await expect(page.locator('.error-notice')).toContainText(
    'Приглашение истекло'
  )
  await page.getByRole('button', { name: 'Отмена', exact: true }).click()
  await expect(page).toHaveURL(/\/login$/)
  await page.goto('/invite#code=invalid')
  await expect(page.getByText('Откройте ссылку из письма.')).toBeVisible()
  expect(
    await page.evaluate(() => sessionStorage.getItem('perk.web.pending-invite'))
  ).toBeNull()
})

test('a late confirmation response cannot approve a different action', async ({
  page
}) => {
  const state = await settingsApi(page)
  state.stepUp = false
  state.holdVerification = true
  await page.goto('/settings')
  await page.getByRole('button', { name: 'Настроить PERK Test WB' }).click()
  await page
    .getByLabel('Новый API-токен')
    .fill('synthetic-test-token-1234567890')
  await page.getByRole('button', { name: 'Сохранить ключ' }).click()
  let confirm = page.getByRole('dialog', { name: 'Подтвердите действие' })
  await confirm.getByRole('button', { name: 'Получить код' }).click()
  await confirm.getByLabel('Код подтверждения').fill('123456')
  await confirm
    .getByRole('button', { name: 'Подтвердить', exact: true })
    .click()
  await expect.poll(() => state.verifyCalls).toBe(1)
  await confirm.getByRole('button', { name: 'Отмена', exact: true }).click()
  await page.getByRole('button', { name: 'Сохранить ключ' }).click()
  confirm = page.getByRole('dialog', { name: 'Подтвердите действие' })
  await expect(confirm).toBeVisible()
  state.releaseVerification?.()
  await expect.poll(() => state.verifyDone).toBe(1)
  await expect(confirm).toBeVisible()
  expect(state.writes).toHaveLength(0)
  await confirm.getByRole('button', { name: 'Отмена', exact: true }).click()
})

test('pending invitation prefills login after a full page reload', async ({
  page
}) => {
  await settingsApi(page, { signedIn: false })
  await page.goto(`/invite#code=${inviteCode}`)
  await page.getByRole('link', { name: 'Войти', exact: true }).click()
  await expect(page).toHaveURL(/\/login$/)
  await page.reload()
  await expect(page.getByLabel('Email или телефон')).toHaveValue(
    'employee@perk.local'
  )
})

for (const provider of ['Wildberries', 'Ozon'])
  test(`connect ${provider} uses confirmation and a fresh form`, async ({
    page
  }) => {
    const state = await settingsApi(page)
    state.stepUp = false
    await page.goto('/settings')
    await page
      .getByRole('button', { name: 'Подключить кабинет', exact: true })
      .click()
    let dialog = page.getByRole('dialog', { name: 'Новый кабинет' })
    await dialog.getByRole('button', { name: provider, exact: true }).click()
    await dialog.getByLabel('Название магазина').fill(`Новый ${provider}`)
    if (provider === 'Ozon')
      await dialog.getByLabel('Client ID', { exact: true }).fill('789101')
    await dialog
      .getByLabel(provider === 'Ozon' ? 'API Key' : 'API-токен Wildberries', {
        exact: true
      })
      .fill('synthetic-connection-key-123456')
    await dialog
      .getByRole('button', { name: 'Подключить', exact: true })
      .click()
    const confirm = page.getByRole('dialog', { name: 'Подтвердите действие' })
    await confirm.getByRole('button', { name: 'Получить код' }).click()
    await confirm.getByLabel('Код подтверждения').fill('000000')
    await confirm
      .getByRole('button', { name: 'Подтвердить', exact: true })
      .click()
    await expect(confirm.locator('.error-notice')).toContainText('Неверный код')
    expect(state.writes).toHaveLength(0)
    await confirm.getByLabel('Код подтверждения').fill('123456')
    await confirm
      .getByRole('button', { name: 'Подтвердить', exact: true })
      .click()
    await expect(
      page.getByRole('button', { name: `Настроить Новый ${provider}` })
    ).toBeVisible()
    expect(state.writes).toHaveLength(1)
    await page
      .getByRole('button', { name: 'Подключить кабинет', exact: true })
      .click()
    dialog = page.getByRole('dialog', { name: 'Новый кабинет' })
    await expect(dialog.getByLabel('Название магазина')).toHaveValue('')
    await expect(
      dialog.getByLabel('API-токен Wildberries', { exact: true })
    ).toHaveValue('')
    await page.keyboard.press('Escape')
  })

test('settings fit a narrow screen and profile is reachable from the header', async ({
  page
}) => {
  await settingsApi(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/settings')
  await page.getByRole('button', { name: 'Настроить PERK Test WB' }).click()
  await expect(page.getByLabel('Новый API-токен')).toBeVisible()
  await expect(
    page.getByRole('button', { name: 'Сохранить ключ' })
  ).toBeVisible()
  await page.screenshot({
    path: 'C:/Users/Artem/Documents/ChatGPT/PERK/outputs/web-settings-20261106/store-mobile.png'
  })
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth
    )
  ).toBe(true)
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: 'Профиль и настройки' }).click()
  await page.getByRole('menuitem', { name: 'Профиль', exact: true }).click()
  await expect(page.getByLabel('Текущий пароль')).toBeVisible()
})
