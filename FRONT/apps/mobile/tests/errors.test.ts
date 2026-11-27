import { AxiosError, AxiosHeaders } from 'axios'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { codeDeliveryMessage } from '@/features/auth/model/channels'

import { errorMessage, retryAfterSeconds } from '@/lib/errors'

function responseError(status: number, retryAfter?: string) {
  const config = { headers: new AxiosHeaders() }
  return new AxiosError(
    'request failed',
    'ERR_BAD_REQUEST',
    config,
    undefined,
    {
      status,
      statusText: 'Error',
      data: {},
      config,
      headers: retryAfter === undefined ? {} : { 'retry-after': retryAfter }
    }
  )
}

afterEach(() => vi.useRealTimers())

describe('ограничение повторной отправки кода', () => {
  it.each(['60', '3600', '1.5'])(
    'учитывает серверный Retry-After: %s',
    header => {
      expect(retryAfterSeconds(responseError(429, header))).toBe(
        Math.ceil(Number(header))
      )
    }
  )

  it('понимает Retry-After в формате HTTP-даты', () => {
    vi.useFakeTimers().setSystemTime(new Date('2026-10-25T00:00:00Z'))
    expect(
      retryAfterSeconds(responseError(429, 'Sun, 25 Oct 2026 00:02:00 GMT'))
    ).toBe(120)
  })

  it('не продлевает истёкшее ограничение', () => {
    vi.useFakeTimers().setSystemTime(new Date('2026-10-25T00:00:00Z'))
    expect(
      retryAfterSeconds(responseError(429, 'Sat, 24 Oct 2026 23:59:00 GMT'))
    ).toBe(0)
  })

  it.each([undefined, 'invalid'])(
    'использует безопасный интервал без корректного заголовка: %s',
    header => {
      expect(retryAfterSeconds(responseError(429, header))).toBe(60)
    }
  )

  it('не приписывает сетевой ошибке или другому статусу лимит отправки', () => {
    expect(retryAfterSeconds(new AxiosError('offline'))).toBe(0)
    expect(retryAfterSeconds(responseError(503, '120'))).toBe(0)
  })

  it('показывает пользователю назначенное сервером время ожидания', () => {
    expect(errorMessage(responseError(429, '3600'))).toBe(
      'Слишком много попыток. Повторите через 60 мин.'
    )
    expect(errorMessage(responseError(429, '30'))).toBe(
      'Слишком много попыток. Повторите через 30 с.'
    )
  })
})

describe('причина сбоя автоматической доставки', () => {
  it('отличает ограничение частоты от сбоя Telegram', () => {
    expect(codeDeliveryMessage('otp_throttled')).toContain('ограничена')
    expect(codeDeliveryMessage('telegram_unavailable')).toContain('Telegram')
    expect(codeDeliveryMessage('telegram_unavailable')).not.toContain(
      'ограничена'
    )
  })
})
