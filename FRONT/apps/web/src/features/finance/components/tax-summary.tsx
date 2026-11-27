import { Settings2 } from 'lucide-react'

import type { FinanceOverview } from '@app/api'

import { Button } from '@/components/ui/button'

import { financeMoney } from '../model/finance-format'

import { ReportHint } from './report-hint'

export function TaxSummary({
  report,
  canEdit,
  onEdit
}: {
  report: FinanceOverview
  canEdit: boolean
  onEdit: () => void
}) {
  return (
    <aside
      className='surface finance-tax'
      aria-labelledby='tax-title'
    >
      <div className='section-heading'>
        <h2 id='tax-title'>Налоги</h2>
        <ReportHint label='О расчёте налогов'>{`Оценка по вашим настройкам. Без вычета входного НДС и годовой сверки.\nНастроено кабинетов: ${report.taxes.configured_stores} из ${report.taxes.total_stores}.`}</ReportHint>
      </div>
      <div className='tax-row'>
        <span>НДС</span>
        <strong>{financeMoney(report.taxes.vat, report.currency)}</strong>
      </div>
      <div className='tax-row'>
        <span>Налог</span>
        <strong>{financeMoney(report.taxes.tax, report.currency)}</strong>
      </div>
      <div className='net-profit'>
        <span>Чистая прибыль</span>
        <strong>
          {financeMoney(report.taxes.net_profit, report.currency)}
        </strong>
      </div>
      {canEdit && (
        <Button
          variant='secondary'
          onClick={onEdit}
        >
          <Settings2 size={15} />
          Настроить налоги
        </Button>
      )}
    </aside>
  )
}
