import { router } from 'expo-router'
import { Wallet } from 'lucide-react-native'
import { useState } from 'react'
import { Pressable, View } from 'react-native'

import {
  Avatar,
  Card,
  Divider,
  EmptyState,
  InfoHint,
  Notice,
  Screen,
  Skeleton,
  Text
} from '@/components/ui'

import { useAuth } from '@/features/auth/providers/AuthProvider'
import { PeriodSelect } from '@/features/periods/components/PeriodSelect'
import {
  type ReportPeriod,
  resolvePeriod
} from '@/features/periods/model/periodRange'
import { StoreSwitcher } from '@/features/workspace/components/StoreSwitcher'
import { UpcomingReport } from '@/features/workspace/components/UpcomingReport'
import { useWorkspace } from '@/features/workspace/providers/WorkspaceProvider'

import { errorMessage } from '@/lib/errors'
import { formatDateRange } from '@/lib/format'

import { FinanceActions } from '../components/FinanceActions'
import { FinanceGroupCard } from '../components/FinanceGroupCard'
import { useFinance } from '../hooks/useFinance'
import { formatFinanceMoney } from '../model/financeFormat'

import { createStyles } from '@/theme'

const periods = [
  { value: 7, label: '7 дней' },
  { value: 30, label: '30 дней' },
  { value: 90, label: '90 дней' }
] as const

export default function FinanceScreen() {
  const styles = useStyles()
  const { user } = useAuth()
  const workspace = useWorkspace()
  const canProfit = workspace.can('profit.read')
  const [period, setPeriod] = useState<ReportPeriod>(30)
  const [expanded, setExpanded] = useState<string | null>(null)
  const query = useFinance(period)
  const data = query.data
  const range = resolvePeriod(period)
  const empty = workspace.status === 'ready' && workspace.stores.length === 0
  if (workspace.stores.length && !workspace.supports('finance'))
    return <UpcomingReport />
  const details = [
    data?.data_sources?.includes('ozon_accruals')
      ? 'Начисления Ozon и финансовые отчёты WB по дате операции. Выручка указана по цене продавца.'
      : 'Данные финансовых отчётов WB. Выручка указана по цене продавца.',
    'К перечислению — расчёт по отчётам; поступление проверяется по банку.',
    ...(canProfit && data?.expenses_exclude_cogs
      ? ['Расходы показаны без себестоимости. Добавьте её для расчёта прибыли.']
      : []),
    ...(data?.is_partial || data?.period_covered === false
      ? ['Показана загруженная часть периода.']
      : []),
    'Налоги — оценка без вычета входного НДС и годовой сверки.',
    ...(data && data.taxes.configured_stores < data.taxes.total_stores
      ? ['Налоговые настройки заполнены не для всех магазинов.']
      : [])
  ].join('\n\n')
  if (!workspace.can('finance.read'))
    return (
      <Screen>
        <Notice message='Нет доступа к финансам.' />
      </Screen>
    )
  return (
    <Screen
      stickyHeader
      headerCenter={
        workspace.stores.length ? <StoreSwitcher compact /> : undefined
      }
      headerRight={
        <Pressable
          onPress={() => router.push('/profile')}
          accessibilityRole='button'
          accessibilityLabel='Профиль'
        >
          <Avatar name={user?.email ?? ''} />
        </Pressable>
      }
      onRefresh={() => query.refetch()}
    >
      <View style={styles.sections}>
        <View>
          <View style={styles.heading}>
            <Text variant='screenTitle'>Финансы</Text>
            <InfoHint
              title='Финансы'
              message={details}
            />
          </View>
          <Text
            variant='caption'
            tone='secondary'
          >
            {formatDateRange(range.date_from, range.date_to)}
          </Text>
        </View>
        <PeriodSelect
          options={periods}
          value={period}
          onChange={setPeriod}
        />
        {query.error && (
          <Notice
            tone='error'
            message={errorMessage(query.error)}
            actionTitle='Повторить'
            onAction={() => void query.refetch()}
          />
        )}
        {!!data?.source_errors?.length && (
          <Notice
            tone='error'
            message='Не удалось обновить начисления Ozon. Показаны сохранённые данные.'
          />
        )}
        {empty ? (
          <Card>
            <EmptyState
              icon={Wallet}
              title='Подключите магазин'
              actionTitle={workspace.isOwner ? 'Подключить магазин' : undefined}
              onAction={
                workspace.isOwner
                  ? () => router.push('/connect-store')
                  : undefined
              }
            />
          </Card>
        ) : !data ? (
          <Skeleton height={280} />
        ) : (
          <>
            <View style={styles.metrics}>
              <Metric
                title='Выручка продавца'
                value={data.totals.seller_revenue}
                currency={data.currency}
              />
              <Metric
                title='Расходы'
                value={data.totals.expenses_before_tax}
                currency={data.currency}
              />
              {canProfit && (
                <Metric
                  title='Прибыль до налогов'
                  value={data.totals.profit_before_tax}
                  currency={data.currency}
                  accent
                />
              )}
              <Metric
                title='К перечислению'
                value={data.totals.settlement}
                currency={data.currency}
              />
            </View>
            <FinanceActions
              date={range.date_from}
              endDate={range.date_to}
              currency={data.currency}
            />
            <View style={styles.groups}>
              {data.groups.map(group => (
                <FinanceGroupCard
                  key={group.key}
                  group={group}
                  currency={data.currency}
                  revenue={data.totals.seller_revenue}
                  expanded={expanded === group.key}
                  onPress={() =>
                    setExpanded(expanded === group.key ? null : group.key)
                  }
                />
              ))}
            </View>
            {data.taxes.configured_stores > 0 && (
              <Card style={styles.taxCard}>
                <Text variant='sectionTitle'>Налоги · оценка</Text>
                <Value
                  title='НДС'
                  amount={data.taxes.vat}
                  currency={data.currency}
                />
                <Value
                  title='Налог'
                  amount={data.taxes.tax}
                  currency={data.currency}
                />
                <Divider />
                <Value
                  title='Чистая прибыль'
                  amount={data.taxes.net_profit}
                  currency={data.currency}
                />
              </Card>
            )}
          </>
        )}
      </View>
    </Screen>
  )
}

function Metric({
  title,
  value,
  currency,
  accent
}: {
  title: string
  value: string | null
  currency: string
  accent?: boolean
}) {
  const styles = useStyles()
  return (
    <Card
      tone={accent ? 'accent' : 'default'}
      style={styles.metric}
    >
      <Text
        variant='caption'
        tone='secondary'
      >
        {title}
      </Text>
      <Text
        variant='value'
        numberOfLines={1}
        adjustsFontSizeToFit
        tabular
      >
        {formatFinanceMoney(value, currency)}
      </Text>
    </Card>
  )
}

function Value({
  title,
  amount,
  currency
}: {
  title: string
  amount: string | null
  currency: string
}) {
  const styles = useStyles()
  return (
    <View style={styles.valueRow}>
      <Text
        variant='label'
        style={styles.valueTitle}
      >
        {title}
      </Text>
      <Text
        variant='bodyStrong'
        tabular
      >
        {formatFinanceMoney(amount, currency)}
      </Text>
    </View>
  )
}

const useStyles = createStyles(({ spacing }) => ({
  sections: { gap: spacing.lg },
  heading: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between'
  },
  metrics: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  metric: { flexGrow: 1, flexBasis: '45%', gap: spacing.sm, minWidth: 130 },
  groups: { gap: spacing.sm },
  taxCard: { gap: spacing.md },
  valueRow: { flexDirection: 'row', gap: spacing.md, alignItems: 'center' },
  valueTitle: { flex: 1 }
}))
