'use client'

import { formatDateRange } from '@app/analytics/format'
import {
  Check,
  History,
  LoaderCircle,
  Plus,
  RefreshCw,
  Upload
} from 'lucide-react'
import { useState } from 'react'

import { AppShell } from '@/components/app-shell'
import { Empty, ErrorNotice, Loading } from '@/components/feedback'
import { ReportPeriodControl } from '@/components/report-period-control'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'

import { useAuth } from '@/features/auth/auth-provider'
import { RequireAuth } from '@/features/auth/require-auth'
import { ConnectStore } from '@/features/workspace/connect-store'
import { useWorkspace } from '@/features/workspace/workspace-provider'

import {
  type ActionSession,
  type FinanceAction,
  FinanceActionDialog
} from './components/finance-action-dialog'
import { FinanceExport } from './components/finance-export'
import { FinanceGroups } from './components/finance-groups'
import { FinanceSummary } from './components/finance-summary'
import { ReportHint } from './components/report-hint'
import { TaxSummary } from './components/tax-summary'
import { useFinance, useRefreshFinance } from './hooks/use-finance'

export function FinancePage() {
  const { user } = useAuth()
  const scope = useWorkspace()
  return (
    <RequireAuth>
      <FinanceContent
        key={`${user?.id}:${scope.accessKey}:${scope.store?.id ?? 'all'}`}
      />
    </RequireAuth>
  )
}
function FinanceContent() {
  const scope = useWorkspace()
  const query = useFinance()
  const refresh = useRefreshFinance()
  const [action, setAction] = useState<ActionSession | null>(null)
  const [saved, setSaved] = useState(false)
  const report = query.data
  const canProfit = scope.can('profit.read')
  const hasFigures =
    report &&
    (Object.values(report.totals).some(value => value != null) ||
      report.groups.some(group => group.amount != null))
  const open = (kind: FinanceAction) => {
    setSaved(false)
    setAction({ kind, id: crypto.randomUUID() })
  }
  const afterSave = async (id: string) => {
    await refresh()
    setAction(current => (current?.id === id ? null : current))
    setSaved(true)
  }
  return (
    <AppShell>
      <div className='page-heading finance-page-heading'>
        <div>
          <div className='finance-title'>
            <h1>Финансы</h1>
            <ReportHint label='О финансовом отчёте'>{`Данные финансовых отчётов WB и начислений Ozon по датам операций. Выручка — по цене продавца.\nК перечислению — расчёт по отчётам, поступление проверяется по банку.${report?.is_partial || report?.period_covered === false ? '\nПоказана загруженная часть периода.' : ''}${report?.expenses_exclude_cogs ? '\nСебестоимость включена не полностью.' : ''}`}</ReportHint>
            {report?.is_loading && (
              <LoaderCircle
                size={15}
                className='animate-spin text-primary'
                aria-label='Финансовые данные загружаются'
              />
            )}
          </div>
          <p>{formatDateRange(query.range.date_from, query.range.date_to)}</p>
        </div>
        <div className='finance-heading-actions'>
          {saved && (
            <span
              role='status'
              className='finance-saved'
            >
              <Check size={14} />
              Сохранено
            </span>
          )}
          <Button
            variant='ghost'
            className='refresh-button'
            aria-label='Обновить финансовый отчёт'
            disabled={
              query.isFetching || scope.loading || !scope.can('finance.read')
            }
            onClick={() => void Promise.all([scope.refresh(), query.refetch()])}
          >
            <RefreshCw size={15} />
            <span>Обновить</span>
          </Button>
        </div>
      </div>
      <ErrorNotice
        error={scope.error}
        onRetry={() => void scope.refresh()}
      />
      {scope.loading ? (
        <Loading />
      ) : !scope.can('finance.read') ? (
        <Empty title='Нет доступа к разделу' />
      ) : !scope.stores.length ? (
        <section className='surface welcome-card'>
          <h2>Подключите магазин</h2>
          <ConnectStore />
        </section>
      ) : !query.supported ? (
        <Empty title='Финансовый отчёт пока недоступен' />
      ) : (
        <>
          <div className='finance-toolbar'>
            <ReportPeriodControl
              value={query.period}
              onChange={query.setPeriod}
              options={[7, 30, 90] as const}
            />
            <div className='finance-actions'>
              <FinanceExport
                range={query.range}
                disabled={!report}
              />
              {scope.can('costs.write') && (
                <Button
                  variant='outline'
                  onClick={() => open('cost')}
                >
                  <Upload size={15} />
                  Себестоимость
                </Button>
              )}
              {scope.can('expenses.write') && (
                <Button
                  disabled={!report?.currency}
                  onClick={() => open('expense')}
                >
                  <Plus size={16} />
                  Добавить расход
                </Button>
              )}
            </div>
          </div>
          <ErrorNotice
            error={query.error}
            onRetry={() => void query.refetch()}
          />
          {!!report?.source_errors?.length && (
            <ErrorNotice
              error={
                new Error(
                  'Не удалось обновить часть финансовых данных. Показан сохранённый отчёт.'
                )
              }
              onRetry={() => void query.refetch()}
            />
          )}
          {query.isPending ? (
            <div className='finance-page-content'>
              <section className='surface'>
                <FinanceSummary
                  pending
                  canProfit={canProfit}
                />
              </section>
              <Skeleton className='h-96 w-full rounded-2xl' />
            </div>
          ) : report ? (
            <div className='finance-page-content'>
              <section className='surface finance-page-summary'>
                <FinanceSummary
                  report={report}
                  canProfit={canProfit}
                />
              </section>
              <div
                className={
                  canProfit ? 'finance-report-grid' : 'finance-report-grid full'
                }
              >
                {hasFigures ? (
                  <FinanceGroups
                    report={report}
                    canProfit={canProfit}
                  />
                ) : (
                  <section className='surface'>
                    <Empty
                      title={
                        report.is_loading
                          ? 'Финансовый отчёт готовится'
                          : 'Нет финансовых данных за период'
                      }
                    />
                  </section>
                )}
                {canProfit && (
                  <TaxSummary
                    report={report}
                    canEdit={scope.can('taxes.write')}
                    onEdit={() => open('tax')}
                  />
                )}
              </div>
              <div className='finance-page-footer'>
                <Button
                  variant='ghost'
                  onClick={() => open('history')}
                >
                  <History size={15} />
                  История внешних расходов
                </Button>
              </div>
            </div>
          ) : !query.error ? (
            <Empty title='Нет финансовых данных за период' />
          ) : null}
        </>
      )}
      {action && scope.can('finance.read') && (
        <FinanceActionDialog
          key={action.id}
          action={action}
          onClose={() => setAction(null)}
          onSaved={() => afterSave(action.id)}
          onRefresh={refresh}
          date={
            action.kind === 'tax' ? query.range.date_from : query.range.date_to
          }
          currency={report?.currency ?? 'RUB'}
        />
      )}
    </AppShell>
  )
}
