import { financeLineShare, financeShare } from '@app/analytics/finance'
import { formatPercent } from '@app/analytics/format'
import { ChevronDown } from 'lucide-react'
import { Fragment, useState } from 'react'

import type { FinanceOverview } from '@app/api'

import { Button } from '@/components/ui/button'

import { financeLineValue, financeMoney } from '../model/finance-format'

import { ReportHint } from './report-hint'

export function FinanceGroups({
  report,
  canProfit
}: {
  report: FinanceOverview
  canProfit: boolean
}) {
  const [opened, setOpened] = useState(new Set<string>(['sales']))
  const groups = report.groups.filter(
    group => canProfit || group.key !== 'cogs'
  )
  const all = groups.length > 0 && groups.every(group => opened.has(group.key))
  return (
    <section
      className='surface finance-ledger'
      aria-labelledby='ledger-title'
    >
      <div className='section-heading'>
        <h2 id='ledger-title'>Доходы и расходы</h2>
        <Button
          variant='ghost'
          size='sm'
          onClick={() =>
            setOpened(all ? new Set() : new Set(groups.map(group => group.key)))
          }
        >
          {all ? 'Свернуть всё' : 'Развернуть всё'}
        </Button>
      </div>
      <div className='table-scroll'>
        <table className='finance-breakdown'>
          <thead>
            <tr>
              <th>Статья</th>
              <th>Доля выручки</th>
              <th>Сумма</th>
            </tr>
          </thead>
          <tbody>
            {groups.map(group => (
              <Fragment key={group.key}>
                <tr className='finance-group-row'>
                  <th scope='row'>
                    <button
                      aria-expanded={opened.has(group.key)}
                      onClick={() =>
                        setOpened(current => {
                          const next = new Set(current)
                          if (next.has(group.key)) next.delete(group.key)
                          else next.add(group.key)
                          return next
                        })
                      }
                    >
                      <ChevronDown size={16} />
                      {group.title}
                    </button>
                    {group.note && (
                      <ReportHint label={`О статье «${group.title}»`}>
                        {group.note}
                      </ReportHint>
                    )}
                  </th>
                  <td>{formatPercent(group.share_percent)}</td>
                  <td>{financeMoney(group.amount, report.currency)}</td>
                </tr>
                {opened.has(group.key) &&
                  group.lines.map(line => (
                    <tr
                      key={line.key}
                      className='finance-line-row'
                    >
                      <th scope='row'>
                        {line.title}
                        {line.note && (
                          <ReportHint label={`О строке «${line.title}»`}>
                            {line.note}
                          </ReportHint>
                        )}
                      </th>
                      <td>
                        {formatPercent(
                          financeLineShare(line, report.totals.seller_revenue)
                        )}
                      </td>
                      <td>{financeLineValue(line, report.currency)}</td>
                    </tr>
                  ))}
              </Fragment>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <th scope='row'>Всего расходов</th>
              <td>
                {formatPercent(
                  financeShare(
                    report.totals.expenses_before_tax,
                    report.totals.seller_revenue
                  )
                )}
              </td>
              <td>
                {financeMoney(
                  report.totals.expenses_before_tax,
                  report.currency
                )}
              </td>
            </tr>
            {canProfit && (
              <tr className='profit'>
                <th scope='row'>Прибыль до налогов</th>
                <td></td>
                <td>
                  {financeMoney(
                    report.totals.profit_before_tax,
                    report.currency
                  )}
                </td>
              </tr>
            )}
          </tfoot>
        </table>
      </div>
    </section>
  )
}
