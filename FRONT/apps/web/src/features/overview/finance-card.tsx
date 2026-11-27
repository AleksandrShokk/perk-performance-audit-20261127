'use client'

import { formatMoney, formatNumber, formatPercent } from '@app/analytics/format'
import { ArrowUpRight } from 'lucide-react'
import Link from 'next/link'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog'

import { FinanceSummary } from '@/features/finance/components/finance-summary'
import { useWorkspace } from '@/features/workspace/workspace-provider'

import type { Overview } from './use-overview'

export function FinanceCard({ overview }: { overview: Overview }) {
  const [open, setOpen] = useState(false)
  const scope = useWorkspace()
  const canProfit = scope.can('profit.read')
  const report = overview.finance.data
  const money = (value: string | null | undefined) =>
    formatMoney(value, report?.currency)
  return (
    <section
      className='surface finance-card'
      id='finance'
      aria-labelledby='finance-title'
    >
      <div className='section-heading'>
        <div className='finance-heading'>
          <h2 id='finance-title'>Финансы</h2>
          <span className='muted'>30 дней</span>
        </div>
        <Button
          variant='ghost'
          size='sm'
          disabled={!report}
          onClick={() => setOpen(true)}
        >
          Финансовый отчёт
          <ArrowUpRight size={15} />
        </Button>
      </div>
      <FinanceSummary
        report={report}
        pending={overview.finance.isPending && overview.finance.isEnabled}
        canProfit={canProfit}
        precise={false}
      />
      <Dialog
        open={open}
        onOpenChange={setOpen}
      >
        <DialogContent className='report-dialog'>
          <DialogHeader>
            <DialogTitle>Финансы за 30 дней</DialogTitle>
            <DialogDescription>
              Начисления и расходы выбранных кабинетов.
            </DialogDescription>
          </DialogHeader>
          <div className='dialog-scroll'>
            <div className='finance-report-summary'>
              <div>
                <span>Выручка продавца</span>
                <strong>{money(report?.totals.seller_revenue)}</strong>
              </div>
              <div>
                <span>Расходы</span>
                <strong>{money(report?.totals.expenses_before_tax)}</strong>
              </div>
              <div>
                <span>К перечислению</span>
                <strong>{money(report?.totals.settlement)}</strong>
              </div>
              {canProfit && (
                <div>
                  <span>Прибыль до налогов</span>
                  <strong>{money(report?.totals.profit_before_tax)}</strong>
                </div>
              )}
            </div>
            {report?.groups
              .filter(group => canProfit || group.key !== 'cogs')
              .map(group => (
                <details
                  className='expense-group'
                  key={group.key}
                >
                  <summary>
                    <span>{group.title}</span>
                    <b>{money(group.amount)}</b>
                  </summary>
                  <div>
                    {group.lines.length ? (
                      group.lines.map(line => (
                        <div
                          className='finance-pair'
                          key={line.key}
                        >
                          <span>{line.title}</span>
                          <b>
                            {line.unit === 'units'
                              ? formatNumber(line.amount)
                              : line.unit === 'percent'
                                ? formatPercent(line.amount)
                                : money(line.amount)}
                          </b>
                        </div>
                      ))
                    ) : (
                      <p className='muted'>Детализации нет</p>
                    )}
                  </div>
                </details>
              ))}
            {canProfit && (
              <div className='finance-pair profit'>
                <span>Чистая прибыль</span>
                <b>{money(report?.taxes.net_profit)}</b>
              </div>
            )}
            <Link
              className='text-link'
              href='/finance'
            >
              Открыть полный отчёт →
            </Link>
          </div>
        </DialogContent>
      </Dialog>
    </section>
  )
}
