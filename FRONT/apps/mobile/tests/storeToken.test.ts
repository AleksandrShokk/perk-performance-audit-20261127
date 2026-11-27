import { AxiosError, AxiosHeaders } from 'axios'
import { describe, expect, it } from 'vitest'

import { replaceStoreTokenSchema } from '@app/schemas'

import {
  connectionLabel,
  tokenExpiryLabel
} from '@/features/stores/model/storeConnection'

import { errorMessage } from '@/lib/errors'

describe('замена ключа WB', () => {
  it('убирает пробелы вокруг ключа до проверки длины', () => {
    const token = 'a'.repeat(30)
    expect(replaceStoreTokenSchema.parse({ token: `  ${token}\n` }).token).toBe(
      token
    )
    expect(
      replaceStoreTokenSchema.safeParse({ token: ' '.repeat(60) }).success
    ).toBe(false)
    expect(
      replaceStoreTokenSchema.safeParse({ token: `   ${'a'.repeat(29)}   ` })
        .success
    ).toBe(false)
  })
  it('не принимает слишком длинный ключ', () => {
    expect(
      replaceStoreTokenSchema.safeParse({ token: 'a'.repeat(8193) }).success
    ).toBe(false)
    expect(
      replaceStoreTokenSchema.safeParse({ token: 'a'.repeat(8192) }).success
    ).toBe(true)
  })
  it('отличает истёкший ключ от отключённого магазина и неизвестного статуса', () => {
    expect(connectionLabel('expired')).toBe('Токен истёк')
    expect(connectionLabel('disconnected')).toBe('Отключён')
    expect(connectionLabel('new-unknown-status')).not.toBe('Подключён')
    expect(connectionLabel(undefined)).toBe('—')
    expect(tokenExpiryLabel(null)).toBe('—')
    expect(tokenExpiryLabel('invalid-date')).toBe('—')
  })
  it.each([
    ['Token belongs to another seller', 'другому продавцу'],
    ['PERK accepts read-only WB tokens only', 'только для чтения'],
    ['Invalid or expired WB token', 'истёк'],
    ['WB rejected the token', 'отклонил']
  ])('объясняет причину отказа: %s', (message, expected) => {
    const config = { headers: new AxiosHeaders() }
    const error = new AxiosError(
      'failed',
      'ERR_BAD_REQUEST',
      config,
      undefined,
      {
        data: { message },
        status: 400,
        statusText: 'Bad request',
        headers: {},
        config
      }
    )
    expect(errorMessage(error)).toContain(expected)
  })
})
