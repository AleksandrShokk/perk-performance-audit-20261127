import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  configureValidationMessages,
  forgotPasswordSchema,
  resetPasswordSchema,
  signUpSchema
} from '@app/schemas'

import type { ProfitReport } from '@app/api'

import { chartSegments } from '@/features/overview/model/chartGeometry'
import { pointLabel } from '@/features/overview/model/chartLabels'
import {
  chartPoints,
  groupChartValues
} from '@/features/overview/model/chartPoints'

import { lastDays, moscowToday } from '@/lib/dates'
import { formatMoney, formatPercent, formatUnits } from '@/lib/format'

afterEach(() => vi.useRealTimers())

describe('сброс пароля', () => {
  it('нормализует адрес и не допускает слабый новый пароль', () => {
    expect(
      forgotPasswordSchema.parse({ email: '  SELLER@example.ru ' }).email
    ).toBe('seller@example.ru')
    expect(
      resetPasswordSchema.safeParse({ new_password: 'short' }).success
    ).toBe(false)
    expect(
      resetPasswordSchema.safeParse({ new_password: 'aaaaaaaaaaaaaaa' }).success
    ).toBe(false)
    expect(
      resetPasswordSchema.safeParse({
        new_password: 'correct horse battery staple'
      }).success
    ).toBe(true)
  })
})

describe('даты и деньги', () => {
  it('считает сутки Москвы, не часового пояса телефона', () => {
    vi.useFakeTimers().setSystemTime(new Date('2026-10-23T22:30:00Z'))
    expect(moscowToday()).toBe('2026-10-24')
    expect(lastDays(7)).toEqual({
      date_from: '2026-10-17',
      date_to: '2026-10-23'
    })
  })
  it('отличает неизвестное от нуля', () => {
    expect(formatMoney(null)).toBe('—')
    expect(formatMoney('0')).toBe('0 ₽')
    expect(formatUnits(null)).toBe('—')
    expect(formatUnits(0)).toBe('0 шт.')
    expect(formatPercent('12.8', { signed: true })).toBe('+12,8%')
  })
  it('округляет денежные строки без потери разрядов', () => {
    expect(formatMoney('9999999999999999.50')).toBe(
      '10\u00a0000\u00a0000\u00a0000\u00a0000\u00a0000 ₽'
    )
    expect(formatMoney('-10.50')).toBe('-11 ₽')
    expect(formatMoney('NaN')).toBe('—')
  })
})

describe('график', () => {
  it('группирует количества, сохраняя неизвестные дни и неполные суммы магазинов', () => {
    const result = groupChartValues(
      new Map([
        ['2026-10-17', '0'],
        ['2026-10-18', '12']
      ]),
      { date_from: '2026-10-17', date_to: '2026-10-23' },
      'month',
      new Set(['2026-10-18'])
    )
    expect(result).toHaveLength(1)
    expect(result[0]).toMatchObject({ amount: '12', partial: true })
  })
  const range = { date_from: '2026-10-01', date_to: '2026-10-03' }
  const report: ProfitReport = {
    ...range,
    status: 'ready',
    is_partial: false,
    period_covered: true,
    currency: 'RUB',
    limit: 100,
    offset: 0,
    daily: [
      { day: '2026-10-01', revenue: '100.50' },
      { day: '2026-10-03', revenue: null }
    ]
  }
  it('рисует нулём только подтверждённый пустой день', () => {
    expect(chartPoints(report, range).map(p => p.value)).toEqual([
      100.5,
      0,
      null
    ])
  })
  it('не додумывает продажи при частичной загрузке', () => {
    expect(
      chartPoints({ ...report, is_partial: true }, range).map(p => p.value)
    ).toEqual([100.5, null, null])
  })
  it('месяц за 7 дней — одна точка с точной суммой', () => {
    const week = { date_from: '2026-10-17', date_to: '2026-10-23' }
    const points = chartPoints(
      {
        ...report,
        ...week,
        daily: [
          { day: '2026-10-17', revenue: '0.10' },
          { day: '2026-10-18', revenue: '0.20' }
        ]
      },
      week,
      'month'
    )
    expect(points).toEqual([
      {
        day: '2026-10-17',
        end: '2026-10-23',
        amount: '0.3',
        value: 0.3,
        partial: false
      }
    ])
    expect(pointLabel(points[0]!, 'month', true)).toBe('окт.')
    expect(pointLabel(points[0]!, 'month')).toBe('17–23 окт.')
  })
  it('группирует деньги без потери старших разрядов', () => {
    const points = chartPoints(
      {
        ...report,
        daily: [
          { day: '2026-10-01', revenue: '9999999999999999.50' },
          { day: '2026-10-02', revenue: '0.51' }
        ]
      },
      range,
      'month'
    )
    expect(points[0]?.amount).toBe('10000000000000000.01')
  })
  it('недели с понедельника, крайние обрезаны периодом', () => {
    const range = { date_from: '2026-09-24', date_to: '2026-10-08' }
    const points = chartPoints(
      { ...report, ...range, daily: [] },
      range,
      'week'
    )
    expect(points.map(point => [point.day, point.end])).toEqual([
      ['2026-09-24', '2026-09-27'],
      ['2026-09-28', '2026-10-04'],
      ['2026-10-05', '2026-10-08']
    ])
    expect(points.every(point => point.amount === '0')).toBe(true)
  })
  it('неделя с неизвестными днями помечена неполной, пустая — разрыв', () => {
    const range = { date_from: '2026-09-28', date_to: '2026-10-11' }
    const points = chartPoints(
      {
        ...report,
        ...range,
        period_covered: false,
        daily: [{ day: '2026-09-30', revenue: '500' }]
      },
      range,
      'week'
    )
    expect(points[0]).toMatchObject({ amount: '500', partial: true })
    expect(points[1]).toMatchObject({
      amount: null,
      value: null,
      partial: false
    })
  })
  it('месяцы режут период по границе месяца', () => {
    const range = { date_from: '2026-09-24', date_to: '2026-10-23' }
    const points = chartPoints({ ...report, ...range }, range, 'month')
    expect(points.map(point => [point.day, point.end])).toEqual([
      ['2026-09-24', '2026-09-30'],
      ['2026-10-01', '2026-10-23']
    ])
  })
  it('не рисует линию при отсутствии отчёта', () => {
    expect(chartPoints(undefined, range).every(p => p.value === null)).toBe(
      true
    )
  })
  it('не соединяет линией разрыв и сохраняет одиночные значения', () => {
    const points = chartPoints(
      {
        ...report,
        period_covered: false,
        daily: [
          { day: '2026-10-01', revenue: '100' },
          { day: '2026-10-03', revenue: '200' }
        ]
      },
      range
    )
    const segments = chartSegments(
      points,
      index => index * 10,
      value => value
    )
    expect(segments).toHaveLength(2)
    expect(segments[0]?.isolated).toEqual({ x: 0, y: 100 })
    expect(segments[1]?.isolated).toEqual({ x: 20, y: 200 })
  })
})

it('использует сгенерированные ограничения и русские ошибки', () => {
  configureValidationMessages()
  const result = signUpSchema.safeParse({
    email: 'bad',
    password: 'short',
    workspace_name: ''
  })
  expect(result.success).toBe(false)
  if (!result.success) {
    expect(
      result.error.issues.some(i => i.message === 'Не меньше 15 символов')
    ).toBe(true)
  }
})
