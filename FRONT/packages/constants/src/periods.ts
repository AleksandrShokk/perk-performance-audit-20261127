/** Стандартные периоды отчётов: сервер готовит их снимки заранее. */
export const REPORT_PERIODS = [
  { days: 7, label: '7 дней' },
  { days: 30, label: '30 дней' },
  { days: 89, label: '90 дней' }
] as const

export type ReportPeriodDays = (typeof REPORT_PERIODS)[number]['days']

export const DEFAULT_REPORT_PERIOD: ReportPeriodDays = 30
