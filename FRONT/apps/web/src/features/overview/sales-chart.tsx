'use client'

import {
  currencySymbol,
  formatDateRange,
  formatMoney,
  formatNumber,
  formatPercent
} from '@app/analytics/format'
import { homePeriod } from '@app/analytics/sales'
import { ArrowUpRight, Info, LoaderCircle } from 'lucide-react'
import { useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from 'recharts'

import { ChoiceSelect } from '@/components/choice-select'
import { Empty } from '@/components/feedback'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Tooltip as Hint,
  TooltipContent,
  TooltipTrigger
} from '@/components/ui/tooltip'

import { type ChartData, type DashboardFilters, metrics } from './chart-data'
import { PeriodControl } from './period-control'
import { ReportCoverage } from './report-coverage'
import type { Overview } from './use-overview'

export function SalesChart({
  overview,
  filters,
  onChange,
  showLink = true
}: {
  overview: Pick<
    Overview,
    'chart' | 'range' | 'salesPending' | 'salesLoading'
  > & {
    reports?: Overview['reports']
    progress?: Overview['progress']
    hasOzon?: boolean
    minDate?: string
    periodPending?: boolean
    historyNotice?: string
  }
  filters: DashboardFilters
  showLink?: boolean
  onChange: (filters: DashboardFilters) => void
}) {
  const [selectedDay, setSelectedDay] = useState<string>()
  const { chart, range } = overview
  const data = chart.points.map(point => ({
    ...point,
    current: number(point.values[filters.metric][filters.unit]),
    previous: number(
      point.values[filters.metric][
        filters.unit === 'amount' ? 'previousAmount' : 'previousUnits'
      ]
    )
  }))
  const requested = homePeriod(filters.period)
  const period =
    requested.date_from === range.date_from &&
    requested.date_to === range.date_to
      ? filters.period
      : range
  const selected = data.find(point => point.day === selectedDay)
  return (
    <section
      className='surface sales-card'
      id='sales'
      aria-label='Продажи'
    >
      <div className='chart-heading'>
        <h2>Продажи</h2>
        <span>{formatDateRange(range.date_from, range.date_to)}</span>
        {overview.salesLoading && (
          <LoaderCircle
            size={14}
            className='animate-spin'
            aria-label='Данные обновляются'
          />
        )}
      </div>
      <div
        className='sales-totals'
        role='group'
        aria-label='Показатель графика'
      >
        {chart.metrics.map(metric => {
          const change =
            filters.unit === 'amount' ? metric.amountChange : metric.unitsChange
          const value = metric[filters.unit].value
          return (
            <button
              key={metric.key}
              className='sales-metric'
              aria-pressed={filters.metric === metric.key}
              onClick={() => onChange({ ...filters, metric: metric.key })}
            >
              <span>{metric.label}</span>
              <strong>
                {filters.unit === 'amount'
                  ? chart.currency
                    ? formatMoney(value, chart.currency)
                    : '—'
                  : `${formatNumber(value)} шт.`}
                {filters.unit === 'amount' &&
                  value != null &&
                  !metric.amount.complete && (
                    <Hint>
                      <TooltipTrigger asChild>
                        <sup aria-label='Сумма неполная'> •</sup>
                      </TooltipTrigger>
                      <TooltipContent>
                        Получены цены не для всех заказов.
                      </TooltipContent>
                    </Hint>
                  )}
              </strong>
              <span
                className={
                  change == null
                    ? 'change'
                    : Number(change) >= 0
                      ? 'change positive'
                      : 'change negative'
                }
              >
                {change == null ? '—' : formatPercent(change, { signed: true })}
                <small>к прошлому периоду</small>
              </span>
            </button>
          )
        })}
      </div>
      <div className='chart-toolbar'>
        <PeriodControl
          value={period}
          minDate={overview.minDate}
          disabled={overview.periodPending}
          onChange={period => onChange({ ...filters, period })}
        />
        <div className='chart-actions'>
          {overview.hasOzon && (
            <ChoiceSelect
              label='Цена Ozon'
              value={filters.priceBasis ?? 'customer'}
              onChange={value =>
                onChange({
                  ...filters,
                  priceBasis: value as 'customer' | 'seller'
                })
              }
              options={[
                { value: 'customer', label: 'Цена реализации' },
                { value: 'seller', label: 'Предельная цена' }
              ]}
            />
          )}

          <ChoiceSelect
            label='Единицы графика'
            value={filters.unit}
            onChange={value =>
              onChange({ ...filters, unit: value as DashboardFilters['unit'] })
            }
            options={[
              {
                value: 'amount',
                label: `Сумма${chart.currency ? `, ${currencySymbol(chart.currency)}` : ''}`,
                disabled: !chart.currency
              },
              { value: 'units', label: 'Количество, шт.' }
            ]}
          />
          <ChoiceSelect
            label='Сравнение графика'
            value={filters.comparison}
            onChange={value =>
              onChange({
                ...filters,
                comparison: value as DashboardFilters['comparison']
              })
            }
            options={[
              { value: 'previous', label: 'С прошлым периодом' },
              { value: 'none', label: 'Без сравнения' }
            ]}
          />
        </div>
      </div>
      <ReportCoverage
        reports={overview.reports ?? []}
        progress={overview.progress ?? []}
        historyNotice={overview.historyNotice}
      />
      <div className='chart-legend'>
        <span>
          <i className='legend-current' />
          {metrics.find(metric => metric.key === filters.metric)?.label}
        </span>
        {filters.comparison === 'previous' && (
          <span>
            <i className='legend-previous' />
            Прошлый период
          </span>
        )}
        <Hint>
          <TooltipTrigger asChild>
            <button
              className='icon-hint'
              aria-label='О показателях графика'
            >
              <Info size={14} />
            </button>
          </TooltipTrigger>
          <TooltipContent className='max-w-72'>
            Выкупы относятся к дню заказа и могут обновляться. Пропуски
            означают, что данные ещё не получены. Сравнение — с предыдущим
            периодом такой же длины. При неполных ценах суммы включают только
            известную часть.
          </TooltipContent>
        </Hint>
      </div>
      <div
        className='chart-container'
        role='group'
        onContextMenu={event => event.preventDefault()}
        onDoubleClick={event => event.preventDefault()}
        onMouseDown={event => event.preventDefault()}
        draggable={false}
        aria-label='Столбчатый график продаж по дням'
      >
        {overview.salesPending ? (
          <Skeleton className='h-full w-full' />
        ) : !data.some(point => point.current != null) ? (
          <Empty
            title={
              overview.salesLoading
                ? 'Загружаем первые дни'
                : 'Нет данных за период'
            }
          />
        ) : (
          <ResponsiveContainer
            width='100%'
            height='100%'
            minWidth={0}
          >
            <BarChart
              data={data}
              barGap={4}
              margin={{ top: 8, right: 4, left: -15, bottom: 0 }}
              onClick={state => {
                if (state?.activeLabel)
                  setSelectedDay(String(state.activeLabel))
              }}
            >
              <CartesianGrid
                vertical={false}
                stroke='var(--border)'
                strokeDasharray='3 5'
              />
              <XAxis
                dataKey='day'
                tickFormatter={day => shortDate(day)}
                axisLine={false}
                tickLine={false}
                minTickGap={28}
                tick={{ fill: 'var(--muted-foreground)', fontSize: 11 }}
                dy={8}
              />
              <YAxis
                axisLine={false}
                tickLine={false}
                tick={{ fill: 'var(--muted-foreground)', fontSize: 11 }}
                tickFormatter={value =>
                  new Intl.NumberFormat('ru-RU', {
                    notation: 'compact',
                    maximumFractionDigits: 0
                  }).format(value)
                }
              />
              <Tooltip
                cursor={{ fill: 'var(--muted)' }}
                content={({ active, payload }) =>
                  active && payload?.[0] ? (
                    <DayTooltip
                      point={payload[0].payload}
                      chart={chart}
                      comparison={filters.comparison === 'previous'}
                    />
                  ) : null
                }
              />
              {filters.comparison === 'previous' && (
                <Bar
                  dataKey='previous'
                  name='Прошлый период'
                  fill='var(--chart-secondary)'
                  radius={[3, 3, 0, 0]}
                  maxBarSize={22}
                  isAnimationActive={false}
                />
              )}
              <Bar
                dataKey='current'
                name={filters.metric}
                fill='var(--primary)'
                radius={[3, 3, 0, 0]}
                maxBarSize={30}
                isAnimationActive={false}
              />
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>
      {selected && (
        <div className='selected-day'>
          <DayTooltip
            point={selected}
            chart={chart}
            comparison={filters.comparison === 'previous'}
          />
          <Button
            variant='ghost'
            size='sm'
            onClick={() => setSelectedDay(undefined)}
          >
            Снять выделение
          </Button>
        </div>
      )}
      {showLink && (
        <a
          className='chart-footer'
          href='/analytics'
        >
          Вся аналитика
          <ArrowUpRight size={15} />
        </a>
      )}
    </section>
  )
}
function number(value: string | null) {
  return value == null ? null : Number(value)
}
function shortDate(day: string, full = false) {
  return new Intl.DateTimeFormat('ru-RU', {
    day: 'numeric',
    month: 'short',
    ...(full ? { year: 'numeric' as const } : {})
  }).format(new Date(`${day}T12:00:00`))
}
function DayTooltip({
  point,
  chart,
  comparison = false
}: {
  point: ChartData['points'][number]
  chart: ChartData
  comparison?: boolean
}) {
  return (
    <div className='chart-tooltip'>
      {(comparison ? [false, true] : [false]).map(past => (
        <section
          className='tooltip-period'
          key={String(past)}
        >
          <strong>
            {past ? 'Прошлый период · ' : ''}
            {shortDate(past ? point.previousDay : point.day, true)}
          </strong>
          {metrics.map(metric => {
            const values = point.values[metric.key]
            return (
              <div key={metric.key}>
                <span>{metric.label}</span>
                <b>
                  {formatNumber(past ? values.previousUnits : values.units)} шт.
                </b>
                <b>
                  {chart.currency
                    ? formatMoney(
                        past ? values.previousAmount : values.amount,
                        chart.currency
                      )
                    : '—'}
                  {(past ? values.previousAmount : values.amount) != null &&
                    !(past
                      ? values.previousAmountComplete
                      : values.amountComplete) && (
                      <sup
                        title='Получены цены не для всех заказов'
                        aria-label='Сумма неполная'
                      >
                        {' '}
                        •
                      </sup>
                    )}
                </b>
              </div>
            )
          })}
        </section>
      ))}
    </div>
  )
}
