import { Stack, router, useLocalSearchParams } from 'expo-router'
import { useState } from 'react'
import { View } from 'react-native'

import { REPORT_PERIODS } from '@app/constants'

import type { BusinessReportParams } from '@app/api'

import { Card, ListRow, Notice, Screen, Skeleton, Text } from '@/components/ui'

import InventoryScreen from '@/features/inventory/screens/InventoryScreen'
import { PeriodSelect } from '@/features/periods/components/PeriodSelect'
import {
  type ReportPeriod,
  rangeError,
  resolvePeriod
} from '@/features/periods/model/periodRange'
import { reportPermission } from '@/features/team/model/permissions'
import { StoreSwitcher } from '@/features/workspace/components/StoreSwitcher'
import { UpcomingReport } from '@/features/workspace/components/UpcomingReport'
import { useWorkspace } from '@/features/workspace/providers/WorkspaceProvider'

import { errorMessage } from '@/lib/errors'
import { formatMoney, formatNumber } from '@/lib/format'

import { ProfitCard } from '../components/ProfitCard'
import { RevenueCard } from '../components/RevenueCard'
import { SalesLeaders } from '../components/SalesLeaders'
import { FunnelReportScreen } from '../funnel/screens/FunnelReportScreen'
import { useBusiness } from '../hooks/useBusiness'

import { createStyles } from '@/theme'

type Topic = NonNullable<BusinessReportParams['topic']>
const TITLES: Record<Topic, string> = {
  overview: 'Обзор',
  finance: 'Финансы',
  sales: 'Выручка',
  orders: 'Заказы',
  buyouts: 'Выкупы и отмены',
  funnel: 'Воронка',
  stock: 'Остатки',
  profit: 'Прибыль'
}
const METRIC_LABELS: Record<string, string> = {
  stock: 'На складе, шт.',
  to_client: 'В пути к покупателям, шт.',
  from_client: 'Возвращается на склад, шт.',
  urgent: 'Требуют внимания, позиций'
}

/** Тема — отдельная страница. Ключ запроса сохраняет магазин, период и вид отчёта. */
export default function ReportScreen({
  defaultTopic,
  tab = false
}: {
  defaultTopic?: Topic
  tab?: boolean
}) {
  const params = useLocalSearchParams<{
    topic?: string
    days?: string
    date_from?: string
    date_to?: string
  }>()
  const selected = defaultTopic ?? params.topic ?? 'sales'
  const topic: Topic = Object.hasOwn(TITLES, selected)
    ? (selected as Topic)
    : 'sales'
  const [period, setPeriod] = useState<ReportPeriod>(() => {
    const custom = {
      date_from: params.date_from ?? '',
      date_to: params.date_to ?? ''
    }
    if (params.date_from && params.date_to && !rangeError(custom)) return custom
    return params.days === '7'
      ? 7
      : params.days === '89' || params.days === '90'
        ? 89
        : 30
  })
  const { can, supports, stores } = useWorkspace()
  if (topic === 'stock')
    return (
      <>
        <Stack.Screen options={{ headerShown: false }} />
        <InventoryScreen />
      </>
    )
  if (
    stores.length &&
    !supports(
      topic === 'orders' || topic === 'buyouts' || topic === 'funnel'
        ? 'analytics'
        : 'finance_details'
    )
  )
    return <UpcomingReport />
  if (!can(reportPermission(topic)))
    return (
      <Screen>
        <Notice message='Нет доступа к этому отчёту.' />
      </Screen>
    )
  if (topic === 'orders' || topic === 'buyouts' || topic === 'funnel') {
    return (
      <FunnelReportScreen
        topic={topic}
        period={period}
        onPeriodChange={setPeriod}
        tab={tab}
      />
    )
  }
  return (
    <FinancialReport
      topic={topic}
      period={period}
      onPeriodChange={setPeriod}
      tab={tab}
    />
  )
}

function FinancialReport({
  topic,
  period,
  onPeriodChange,
  tab
}: {
  topic: Topic
  period: ReportPeriod
  onPeriodChange: (period: ReportPeriod) => void
  tab: boolean
}) {
  const styles = useStyles()
  const query = useBusiness(period, topic)
  const data = query.data
  const { allStores, selectStore } = useWorkspace()
  const range = resolvePeriod(period)
  const hasMetrics = topic === 'stock'
  const completeStores = !data
    ? 0
    : topic === 'sales' || topic === 'profit'
      ? data.stores.filter(
          item =>
            item.finance.status === 'ready' &&
            item.finance.period_covered &&
            !item.finance.is_partial &&
            item.connection_status === 'connected'
        ).length
      : hasMetrics
        ? (data.metrics_complete_stores ?? 0)
        : data.complete_stores

  return (
    <Screen
      bottomInset={!tab}
      logo={tab}
      onRefresh={() => query.refetch()}
    >
      <View style={[styles.sections, !tab && styles.detail]}>
        <StoreSwitcher />
        <Text variant='screenTitle'>{TITLES[topic]}</Text>
        <PeriodSelect
          options={REPORT_PERIODS.map(item => ({
            value: item.days,
            label: item.label
          }))}
          value={period}
          onChange={onPeriodChange}
        />
        {query.error && (
          <Notice
            tone='error'
            message={errorMessage(query.error)}
            actionTitle='Повторить'
            onAction={() => void query.refetch()}
          />
        )}
        {!data ? (
          <Skeleton height={280} />
        ) : (
          <>
            {completeStores < data.total_stores && (
              <Notice
                message={`Готово магазинов: ${completeStores} из ${data.total_stores}`}
              />
            )}
            {topic === 'sales' && (
              <RevenueCard
                report={data.finance}
                range={range}
              />
            )}
            {topic === 'profit' && (
              <>
                <ProfitCard report={data.finance} />
                <Card>
                  <Text variant='sectionTitle'>Расчёт за период</Text>
                  <Value
                    title='Выручка'
                    value={formatMoney(
                      data.finance.summary?.revenue,
                      data.finance.currency
                    )}
                  />
                  <Value
                    title='Себестоимость'
                    value={formatMoney(
                      data.finance.summary?.cogs,
                      data.finance.currency
                    )}
                  />
                  <Value
                    title='Внешние расходы'
                    value={formatMoney(
                      data.finance.summary?.external_expenses,
                      data.finance.currency
                    )}
                  />
                </Card>
              </>
            )}
            {hasMetrics && (
              <Card>
                <Text variant='sectionTitle'>{TITLES[topic]}</Text>
                {data.metrics ? (
                  Object.entries(data.metrics).map(([key, value]) => (
                    <Value
                      key={key}
                      title={METRIC_LABELS[key] ?? key}
                      value={formatNumber(value)}
                    />
                  ))
                ) : (
                  <Text tone='secondary'>Отчёт ещё готовится</Text>
                )}
                {(data.metrics_complete_stores ?? 0) < data.total_stores && (
                  <Text
                    variant='caption'
                    tone='secondary'
                  >
                    Полные данные: {data.metrics_complete_stores} из{' '}
                    {data.total_stores} магазинов.
                  </Text>
                )}
              </Card>
            )}
            {data.stores.map(item => (
              <View
                key={item.id}
                style={styles.sections}
              >
                {allStores && (
                  <Card>
                    <ListRow
                      title={item.name}
                      subtitle={
                        item.connection_status === 'connected'
                          ? 'Открыть магазин'
                          : 'Проверьте подключение'
                      }
                      onPress={() => selectStore(item.id)}
                    />
                    {hasMetrics &&
                      item.metrics &&
                      Object.entries(item.metrics).map(([key, value]) => (
                        <Value
                          key={key}
                          title={METRIC_LABELS[key] ?? key}
                          value={formatNumber(value)}
                        />
                      ))}
                    {(topic === 'sales' || topic === 'profit') && (
                      <Value
                        title='Выручка'
                        value={formatMoney(
                          item.finance.summary?.revenue,
                          item.finance.currency
                        )}
                      />
                    )}
                  </Card>
                )}
                {topic === 'sales' && <SalesLeaders report={item.finance} />}
              </View>
            ))}
            {data.stores.length === 0 && (
              <Notice
                message='Подключите магазин, чтобы увидеть статистику.'
                actionTitle='Подключить'
                onAction={() => router.push('/connect-store')}
              />
            )}
          </>
        )}
      </View>
    </Screen>
  )
}

function Value({ title, value }: { title: string; value: string }) {
  const styles = useStyles()
  return (
    <View style={styles.value}>
      <Text
        tone='secondary'
        style={styles.label}
      >
        {title}
      </Text>
      <Text
        variant='bodyStrong'
        tabular
      >
        {value}
      </Text>
    </View>
  )
}

const useStyles = createStyles(({ spacing }) => ({
  detail: { marginTop: spacing.huge },
  sections: { gap: spacing.lg },
  value: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: spacing.md,
    marginVertical: spacing.sm
  },
  label: { flex: 1 }
}))
