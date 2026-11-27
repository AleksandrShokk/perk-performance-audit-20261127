import { AxiosError, AxiosHeaders } from 'axios'
import { describe, expect, it } from 'vitest'
import { z } from 'zod'

import { configureValidationMessages } from '@app/schemas'

import { apiErrorMessage } from '@app/api'

import { errorMessage } from '@/lib/errors'

function failure(status: number, data: unknown, code = 'ERR_BAD_REQUEST') {
  const config = { headers: new AxiosHeaders() }
  return new AxiosError('Request failed', code, config, undefined, {
    status,
    data,
    headers: {},
    statusText: 'Error',
    config
  })
}

describe('общие русские ошибки', () => {
  it('переводит ошибку сервисного токена из прежней версии API', () => {
    const value = failure(400, {
      detail: 'Production requires a WB service token issued for PERK'
    })
    expect(errorMessage(value)).toBe(
      'Для подключения WB нужен сервисный токен, выданный для PERK.'
    )
    expect(errorMessage(value)).toBe(apiErrorMessage(value))
  })

  it.each([
    { message: 'Проверьте токен магазина.' },
    { detail: { code: 'token_invalid', message: 'Проверьте токен магазина.' } },
    { detail: 'Проверьте токен магазина.' }
  ])('поддерживает все форматы ответа API', data => {
    expect(errorMessage(failure(400, data))).toBe('Проверьте токен магазина.')
  })

  it('не показывает неизвестные английские ошибки или содержимое HTML-ответа', () => {
    expect(errorMessage(failure(502, '<html>Bad Gateway</html>'))).toMatch(
      /[а-яё]/i
    )
    expect(
      errorMessage(failure(400, { message: 'Provider internal error' }))
    ).toBe('Проверьте введённые данные.')
    expect(errorMessage(new Error('Unexpected token'))).not.toContain(
      'Unexpected'
    )
    expect(errorMessage(new Error('Не удалось прочитать файл.'))).toBe(
      'Не удалось прочитать файл.'
    )
  })

  it('различает отсутствие сети и время ожидания', () => {
    expect(errorMessage(new AxiosError('Network Error'))).toContain('интернет')
    expect(errorMessage(failure(0, null, 'ECONNABORTED'))).toContain('вовремя')
  })

  it('использует русскую локаль для оставшихся ошибок Zod', () => {
    configureValidationMessages()
    const parsed = z.number().multipleOf(3).safeParse(4)
    expect(parsed.success).toBe(false)
    if (!parsed.success)
      expect(parsed.error.issues[0].message).toMatch(/[а-яё]/i)
  })
})
