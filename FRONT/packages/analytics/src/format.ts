import { format, isSameMonth, isSameYear, isToday, parseISO } from 'date-fns'
import { ru } from 'date-fns/locale'
import { Decimal } from 'decimal.js'

/** Неизвестное значение показываем прочерком; известный ноль — нулём. */
export const UNKNOWN = '—'

const CURRENCY_SYMBOLS: Record<string, string> = {
  RUB: '₽',
  KZT: '₸',
  BYN: 'Br',
  KGS: 'сом',
  AMD: '֏',
  UZS: 'сум',
  USD: '$',
  EUR: '€',
  CNY: '¥'
}

type Amount = string | number | null | undefined

function toNumber(value: Amount): number | null {
  if (value === null || value === undefined || value === '') return null
  const number = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(number) ? number : null
}

export function currencySymbol(currency = 'RUB') {
  return CURRENCY_SYMBOLS[currency] ?? currency
}

/** Число с пробелами между разрядами: 1 284 600. */
export function formatNumber(value: Amount, fractionDigits = 0) {
  const number = toNumber(value)
  if (number === null) return UNKNOWN
  return new Intl.NumberFormat('ru-RU', {
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits
  }).format(number)
}

/** Сумма отдельно от знака валюты — для крупных показателей, где валюта меньше. */
export function moneyParts(value: Amount, currency = 'RUB') {
  if (value === null || value === undefined || value === '')
    return { amount: UNKNOWN, symbol: '' }
  try {
    const amount = new Decimal(value).toDecimalPlaces(0, Decimal.ROUND_HALF_UP)
    if (!amount.isFinite()) return { amount: UNKNOWN, symbol: '' }
    return {
      amount: amount.toFixed(0).replace(/\B(?=(\d{3})+(?!\d))/g, '\u00a0'),
      symbol: currencySymbol(currency)
    }
  } catch {
    return { amount: UNKNOWN, symbol: '' }
  }
}

/** 1 284 600 ₽ или «—». */
export function formatMoney(value: Amount, currency = 'RUB') {
  const { amount, symbol } = moneyParts(value, currency)
  return symbol ? `${amount} ${symbol}` : amount
}

/** 342 шт. или «—». */
export function formatUnits(value: number | null | undefined) {
  return value === null || value === undefined
    ? UNKNOWN
    : `${formatNumber(value)} шт.`
}

/** 12.8 → «+12,8%». */
export function formatPercent(value: Amount, { signed = false } = {}) {
  const number = toNumber(value)
  if (number === null) return UNKNOWN
  const sign = signed && number > 0 ? '+' : ''
  return `${sign}${formatNumber(number, Number.isInteger(number) ? 0 : 1)}%`
}

/** «24–30 сентября», «28 сентября – 4 октября», с годом, если он не текущий. */
export function formatDateRange(from: string, to: string) {
  const start = parseISO(from)
  const end = parseISO(to)
  const dayMonth = (date: Date) =>
    format(date, isSameYear(date, new Date()) ? 'd MMMM' : 'd MMMM yyyy', {
      locale: ru
    })

  if (from === to) return dayMonth(start)
  return isSameMonth(start, end)
    ? `${format(start, 'd')}–${dayMonth(end)}`
    : `${dayMonth(start)} – ${dayMonth(end)}`
}

/** «1 сент.» — подписи оси графика. */
export function formatShortDate(day: string) {
  return format(parseISO(day), 'd MMM', { locale: ru })
}

/** «24 сентября». */
export function formatLongDate(day: string) {
  return format(parseISO(day), 'd MMMM', { locale: ru })
}

/** «Обновлено в 10:42» или «Обновлено 23 окт. в 10:42». */
export function formatUpdatedAt(moment: string) {
  const date = new Date(moment)
  return isToday(date)
    ? `Обновлено в ${format(date, 'HH:mm')}`
    : `Обновлено ${format(date, 'd MMM в HH:mm', { locale: ru })}`
}

/** Склонение: plural(5, ['товар', 'товара', 'товаров']) → «товаров». */
export function plural(
  count: number,
  [one, few, many]: [string, string, string]
) {
  const mod10 = count % 10
  const mod100 = count % 100
  if (mod10 === 1 && mod100 !== 11) return one
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few
  return many
}
