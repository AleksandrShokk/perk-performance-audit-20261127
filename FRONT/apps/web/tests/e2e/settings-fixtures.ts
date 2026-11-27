import type { Page } from '@playwright/test'

import { mockApi, ozon, wb, wid } from './fixtures'

export const inviteCode = `pw_${'A'.repeat(43)}`
export const employeeId = '30000000-0000-4000-8000-000000000002'
export async function settingsApi(
  page: Page,
  options: { signedIn?: boolean; role?: string; invited?: boolean } = {}
) {
  const auth = await mockApi(page, options)
  const state = {
    auth,
    role: options.role ?? 'owner',
    email: 'web-test@perk.local',
    stepUp: true,
    sendCalls: 0,
    verifyCalls: 0,
    verifyDone: 0,
    verifyDelay: 0,
    holdVerification: false,
    releaseVerification: null as (() => void) | null,
    teamCalls: 0,
    checks: 0,
    writes: [] as { path: string; body: Record<string, unknown> | null }[],
    inviteDelay: 0,
    inviteFails: false,
    expired: false,
    accepted: !options.invited,
    registered: null as Record<string, unknown> | null,
    stores: [
      {
        id: wb,
        name: 'PERK Test WB',
        marketplace: 'wildberries',
        connection_status: 'expired',
        reports_available: true,
        features: ['catalog', 'analytics', 'finance', 'inventory', 'supplies'],
        last_checked_at: null
      },
      {
        id: ozon,
        name: 'PERK Test Ozon',
        marketplace: 'ozon',
        connection_status: 'connected',
        reports_available: true,
        features: ['catalog', 'analytics', 'finance', 'inventory', 'supplies'],
        last_checked_at: null
      }
    ],
    members: [
      {
        user_id: '30000000-0000-4000-8000-000000000001',
        email: 'web-test@perk.local',
        role: 'owner',
        permissions: [],
        store_ids: null as string[] | null,
        is_creator: true
      },
      {
        user_id: employeeId,
        email: 'employee@perk.local',
        role: 'manager',
        permissions: ['analytics.read', 'inventory.read'],
        store_ids: [wb] as string[] | null,
        is_creator: false
      }
    ],
    invites: [] as Record<string, unknown>[]
  }
  const challenge = {
    challenge_id: '40000000-0000-4000-8000-000000000001',
    channel: 'telegram',
    destination: '+7 *** ***-00-01',
    expires_in: 300,
    resend_after: 60
  }
  await page.route('**/api/v1/**', async route => {
    const req = route.request(),
      path = new URL(req.url()).pathname,
      method = req.method()
    const body = req.postData()
      ? (req.postDataJSON() as Record<string, unknown>)
      : null
    const reply = (
      data: unknown,
      status = 200,
      headers: Record<string, string> = {}
    ) =>
      route.fulfill({
        status,
        contentType: 'application/json',
        body: JSON.stringify(data),
        headers
      })
    const error = (code: string, message: string, status = 403) =>
      reply({ detail: { code, message } }, status)
    if (!['GET', 'HEAD'].includes(method) && auth.signedIn)
      auth.csrfValid &&= req.headers()['x-csrf-token'] === 'pc_test'
    if (path.endsWith('/auth/me'))
      return auth.signedIn
        ? reply({
            id: '30000000-0000-4000-8000-000000000001',
            email: state.email,
            email_verified: true,
            phone: auth.phoneBound ? '+7 *** ***-00-01' : null,
            phone_channel: 'telegram',
            totp_enabled: false,
            strong_factor_enabled: auth.phoneBound,
            session_mfa_verified: auth.mfa,
            step_up_valid: state.stepUp,
            strong_step_up_valid: state.stepUp,
            mfa_enabled: auth.phoneBound
          })
        : reply({ detail: 'Authentication required' }, 401)
    if (path.endsWith('/auth/step-up/send')) {
      state.sendCalls++
      return reply(challenge, 202)
    }
    if (path.endsWith('/auth/step-up/verify')) {
      state.verifyCalls++
      if (body?.code !== '123456')
        return error('otp_invalid', 'Неверный код', 400)
      if (state.verifyDelay)
        await new Promise(resolve => setTimeout(resolve, state.verifyDelay))
      if (state.holdVerification)
        await new Promise<void>(resolve => {
          state.releaseVerification = resolve
        })
      state.verifyDone++
      state.stepUp = true
      return reply({ message: 'Подтверждено' })
    }
    if (path === '/api/v1/workspaces')
      return reply(
        state.accepted
          ? [
              {
                id: wid,
                name: 'PERK Test',
                role: state.role,
                permissions: state.role === 'viewer' ? ['inventory.read'] : [],
                store_ids: null
              }
            ]
          : []
      )
    if (path === `/api/v1/workspaces/${wid}/stores` && method === 'GET')
      return reply(state.stores)
    if (
      method === 'POST' &&
      (path.endsWith('/stores/wildberries') || path.endsWith('/stores/ozon'))
    ) {
      if (!state.stepUp)
        return error('strong_step_up_required', 'Подтвердите действие')
      state.writes.push({ path, body })
      const store = {
        ...state.stores[path.endsWith('/ozon') ? 1 : 0]!,
        id: '20000000-0000-4000-8000-000000000003',
        name: String(body?.name),
        connection_status: 'connected'
      }
      state.stores.push(store)
      return reply(store, 201)
    }
    if (path.endsWith('/connection'))
      return reply({
        status: path.includes(wb)
          ? state.stores[0]!.connection_status
          : 'connected',
        client_id: path.includes(ozon) ? '123456' : null,
        scopes: ['catalog', 'analytics'],
        expires_at: '2027-01-01T00:00:00Z',
        checked_at: '2026-11-06T08:00:00Z'
      })
    if (path.endsWith('/check')) {
      if (!state.stepUp)
        return error('strong_step_up_required', 'Подтвердите действие')
      state.checks++
      state.stores[0]!.connection_status = 'connected'
      return reply({
        status: 'connected',
        scopes: [],
        checked_at: new Date().toISOString()
      })
    }
    const store = state.stores.find(
      s => path === `/api/v1/workspaces/${wid}/stores/${s.id}`
    )
    if (store && method === 'PATCH') {
      state.writes.push({ path, body })
      store.name = String(body?.name)
      return reply(store)
    }
    if (path.endsWith('/credential') || path.endsWith('/ozon-credential')) {
      if (!state.stepUp)
        return error('strong_step_up_required', 'Подтвердите действие')
      if (body?.api_key === 'WRONG-SELLER-KEY')
        return error(
          'seller_mismatch',
          'Ключ принадлежит другому продавцу',
          409
        )
      state.writes.push({ path, body })
      const target = state.stores.find(s => path.includes(s.id))!
      target.connection_status = 'connected'
      return reply(target)
    }
    if (path.endsWith('/team')) {
      state.teamCalls++
      return reply({ members: state.members, invites: state.invites })
    }
    if (path === `/api/v1/workspaces/${wid}/invites`) {
      if (!state.stepUp)
        return error('step_up_required', 'Подтвердите действие')
      state.writes.push({ path, body })
      const invite = {
        ...body,
        id: '50000000-0000-4000-8000-000000000001',
        created_at: new Date().toISOString(),
        expires_at: '2027-01-01T00:00:00Z'
      }
      state.invites.push(invite)
      if (state.inviteDelay)
        await new Promise(resolve => setTimeout(resolve, state.inviteDelay))
      return state.inviteFails
        ? error('email_delivery_failed', 'Не удалось отправить письмо', 503)
        : reply(invite, 201)
    }
    if (path.includes(`/workspaces/${wid}/invites/`)) {
      state.writes.push({ path, body })
      if (method === 'DELETE') state.invites = []
      return reply({ message: 'Готово' })
    }
    if (path.includes(`/members/`) && ['PUT', 'DELETE'].includes(method)) {
      if (!state.stepUp)
        return error('strong_step_up_required', 'Подтвердите действие')
      state.writes.push({ path, body })
      if (method === 'DELETE')
        state.members = state.members.filter(m => !path.endsWith(m.user_id))
      else {
        const member = state.members.find(m => path.endsWith(m.user_id))!
        Object.assign(member, body)
        if (member.user_id === state.members[0]?.user_id)
          state.role = member.role
      }
      return reply(
        state.members.find(m => path.endsWith(m.user_id)) ?? {
          message: 'Удалён'
        }
      )
    }
    if (path === '/api/v1/invites/preview')
      return state.expired
        ? error('invite_expired', 'Приглашение истекло', 410)
        : reply({
            email: 'employee@perk.local',
            workspace_name: 'PERK Test',
            role: 'manager',
            permissions: ['analytics.read', 'inventory.read'],
            store_ids: [wb],
            expires_at: '2027-01-01T00:00:00Z'
          })
    if (path === '/api/v1/invites/accept') {
      state.writes.push({ path, body })
      state.accepted = true
      return reply({ workspace_id: wid })
    }
    if (path.endsWith('/auth/register')) {
      state.registered = body
      state.email = String(body?.email)
      return reply(
        { ...challenge, channel: 'email', destination: state.email },
        202
      )
    }
    if (path.endsWith('/auth/password') || path.endsWith('/auth/logout-all')) {
      if (!state.stepUp)
        return error('step_up_required', 'Подтвердите действие')
      if (path.endsWith('/password') && body?.password === 'incorrect-password')
        return error('invalid_password', 'Неверный текущий пароль', 400)
      state.writes.push({ path, body })
      auth.signedIn = false
      return reply({ message: 'Готово' }, 200, {
        'set-cookie': 'perk_csrf=; Path=/; Max-Age=0'
      })
    }
    return route.fallback()
  })
  return state
}
