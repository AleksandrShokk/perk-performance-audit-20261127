import { expect, test } from '@playwright/test'

import { mockApi } from './fixtures'

test('two tabs refresh one browser session once', async ({ page, context }) => {
  const second = await context.newPage()
  await mockApi(page)
  await mockApi(second)
  await context.addCookies([
    { name: 'perk_csrf', value: 'pc_old', url: 'http://localhost:3000' }
  ])
  let refreshes = 0
  for (const tab of [page, second]) {
    await tab.route('**/api/v1/auth/refresh', async route => {
      refreshes++
      await new Promise(resolve => setTimeout(resolve, 100))
      await route.fulfill({
        json: { csrf_token: 'pc_new', expires_in: 900, mfa_required: false },
        headers: { 'set-cookie': 'perk_csrf=pc_new; Path=/; SameSite=Strict' }
      })
    })
    await tab.route('**/insights/funnel?**', async route => {
      const cookie = route.request().headers().cookie ?? ''
      if (cookie.includes('perk_csrf=pc_old'))
        await route.fulfill({ status: 401, json: { detail: 'expired' } })
      else await route.fallback()
    })
  }
  await Promise.all([page.goto('/analytics'), second.goto('/analytics')])
  await expect.poll(() => refreshes).toBe(1)
  await expect(
    page.getByRole('heading', { name: 'Аналитика', exact: true })
  ).toBeVisible()
  await expect(
    second.getByRole('heading', { name: 'Аналитика', exact: true })
  ).toBeVisible()
  await expect(page.getByText('Войдите в аккаунт')).toHaveCount(0)
  await second.close()
})

test('CSP uses a fresh nonce and blocks an untrusted inline script', async ({
  page
}) => {
  await mockApi(page)
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  const first = await page.goto('/login')
  const policy = first!.headers()['content-security-policy']
  const nonce = policy.match(/'nonce-([^']+)'/)?.[1]
  expect(nonce).toBeTruthy()
  expect(policy).toContain("object-src 'none'")
  expect(policy).not.toContain("'unsafe-eval'")
  expect(
    await page
      .locator('script')
      .evaluateAll(scripts => scripts.some(script => !!script.nonce))
  ).toBe(true)
  expect(errors).toEqual([])
  const second = await page.goto('/login')
  expect(second!.headers()['content-security-policy']).not.toContain(
    `'nonce-${nonce}'`
  )
  // Insert through the HTML parser: DevTools evaluation itself is trusted by the browser.
  await page.route(
    '**/login',
    async route => {
      const response = await route.fetch()
      const body = (await response.text()).replace(
        '</body>',
        '<script>window.__perkCspProbe = 1</script></body>'
      )
      await route.fulfill({ response, body })
    },
    { times: 1 }
  )
  await page.goto('/login')
  const injected = await page.evaluate(() => '__perkCspProbe' in window)
  expect(injected).toBe(false)
})
