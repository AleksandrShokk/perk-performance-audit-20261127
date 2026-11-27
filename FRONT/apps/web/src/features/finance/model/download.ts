import type { FinanceOverview } from '@app/api'

export { downloadFile } from '@/lib/download'

/** Text from stores/marketplaces is escaped so spreadsheet formulas cannot execute. */
export function summaryCSV(
  report: FinanceOverview,
  store: string,
  canProfit: boolean
) {
  const quote = (value: string) =>
    `"${(/^[=+@\-\t\r\n]/.test(value) && !/^-?\d+(?:[.,]\d+)?$/.test(value) ? `'${value}` : value).replaceAll('"', '""')}"`
  const amount = (value: string | null) =>
    value == null ? '' : value.replace('.', ',')
  const rows = [
    [store, report.date_from, report.date_to],
    [
      'Статус',
      report.is_partial || !report.period_covered
        ? 'Частичный отчёт'
        : 'Готовый отчёт'
    ],
    ['Статья', 'Сумма', 'Валюта'],
    ['Выручка продавца', amount(report.totals.seller_revenue), report.currency],
    ['Расходы', amount(report.totals.expenses_before_tax), report.currency],
    ...(canProfit
      ? [
          [
            'Прибыль до налогов',
            amount(report.totals.profit_before_tax),
            report.currency
          ]
        ]
      : []),
    ['К перечислению', amount(report.totals.settlement), report.currency],
    ...report.groups
      .filter(group => canProfit || group.key !== 'cogs')
      .map(group => [group.title, amount(group.amount), report.currency])
  ]
  return '\uFEFF' + rows.map(row => row.map(quote).join(';')).join('\r\n')
}
