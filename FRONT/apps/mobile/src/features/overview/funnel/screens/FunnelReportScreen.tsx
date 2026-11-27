import { router } from 'expo-router'
import { View } from 'react-native'

import { REPORT_PERIODS } from '@app/constants'

import {
  Card,
  InfoHint,
  ListRow,
  Notice,
  Screen,
  Skeleton,
  Text
} from '@/components/ui'

import { PeriodSelect } from '@/features/periods/components/PeriodSelect'
import {
  type ReportPeriod,
  resolvePeriod
} from '@/features/periods/model/periodRange'
import { StoreSwitcher } from '@/features/workspace/components/StoreSwitcher'
import { useWorkspace } from '@/features/workspace/providers/WorkspaceProvider'

import { errorMessage } from '@/lib/errors'
import {
  formatDateRange,
  formatMoney,
  formatNumber,
  formatPercent
} from '@/lib/format'

import { BuyoutHint } from '../../components/BuyoutHint'
import { useFunnel } from '../hooks/useFunnel'
import { summarizeFunnel } from '../model/funnelMetrics'

import { createStyles } from '@/theme'

export type FunnelTopic = 'orders' | 'buyouts' | 'funnel'
const TITLES = {
  orders: 'Заказы',
  buyouts: 'Выкупы и отмены',
  funnel: 'Воронка'
}
type Summary = ReturnType<typeof summarizeFunnel>

/** Существующие разделы аналитики используют один отчёт WB и одинаковые правила. */
export function FunnelReportScreen({
  topic,
  period,
  onPeriodChange,
  tab
}: {
  topic: FunnelTopic
  period: ReportPeriod
  onPeriodChange: (period: ReportPeriod) => void
  tab: boolean
}) {
  const styles = useStyles()
  const range = resolvePeriod(period)
  const funnel = useFunnel(range)
  const { allStores, selectStore, status, refetch } = useWorkspace()
  const summary = summarizeFunnel(funnel.reports)
  const hasOzon = funnel.stores.some(store => store.marketplace === 'ozon')
  const explanation =
    'Заказы, выкупы и отмены относятся к дате исходного заказа.' +
    (hasOzon && summary.opens === null
      ? ' Просмотры и корзины Ozon зависят от доступа к аналитике.'
      : '')
  return (
    <Screen
      logo={tab}
      bottomInset={!tab}
      onRefresh={async () => {
        await funnel.refresh()
        if (status === 'error') await refetch()
      }}
    >
      <View style={[styles.sections, !tab && styles.detail]}>
        <StoreSwitcher />
        <View style={styles.heading}>
          <Text
            variant='screenTitle'
            style={styles.title}
          >
            {TITLES[topic]}
          </Text>
          <InfoHint
            title={TITLES[topic]}
            message={
              summary.complete
                ? explanation
                : 'Доступна загруженная часть периода. ' + explanation
            }
          />
        </View>
        <PeriodSelect
          options={REPORT_PERIODS.map(item => ({
            value: item.days,
            label: item.label
          }))}
          value={period}
          onChange={onPeriodChange}
        />
        <Text
          variant='caption'
          tone='secondary'
        >
          {formatDateRange(range.date_from, range.date_to)} · по дате заказа
        </Text>
        {funnel.error && (
          <Notice
            tone='error'
            message={errorMessage(funnel.error)}
            actionTitle='Повторить'
            onAction={() => void funnel.refresh()}
          />
        )}
        {status === 'error' && (
          <Notice
            tone='error'
            message='Не удалось загрузить магазины'
            actionTitle='Повторить'
            onAction={() => void refetch()}
          />
        )}
        {funnel.pending || status === 'loading' ? (
          <Skeleton height={280} />
        ) : !funnel.stores.length ? (
          <Notice
            message='Подключите магазин, чтобы увидеть статистику.'
            actionTitle='Подключить'
            onAction={() => router.push('/connect-store')}
          />
        ) : !funnel.hasData ? (
          <Notice message='Данных пока нет' />
        ) : (
          <>
            <Card>
              <Text variant='sectionTitle'>{TITLES[topic]}</Text>
              <FunnelValues
                topic={topic}
                summary={summary}
              />
            </Card>
            {allStores &&
              funnel.stores.map(item => (
                <Card key={item.id}>
                  <ListRow
                    title={item.name}
                    subtitle='Открыть магазин'
                    onPress={() => selectStore(item.id)}
                  />
                  <FunnelValues
                    topic={topic}
                    summary={summarizeFunnel([item.report])}
                  />
                </Card>
              ))}
          </>
        )}
      </View>
    </Screen>
  )
}

function FunnelValues({
  topic,
  summary
}: {
  topic: FunnelTopic
  summary: Summary
}) {
  const styles = useStyles()
  const money = (value: string | null) =>
    formatMoney(value, summary.currency ?? undefined)
  const rows: [string, string][] = [
    ['Заказано', formatNumber(summary.orders)],
    ['Сумма заказов', `${money(summary.ordersAmount)}`],
    ['Выкуплено', formatNumber(summary.buyouts)],
    ['Сумма выкупов', `${money(summary.buyoutsAmount)}`],
    ['Отмены и возвраты', formatNumber(summary.cancellations)],
    ['Сумма отмен и возвратов', `${money(summary.cancellationsAmount)}`],
    ['Доля выкупа', formatPercent(summary.buyoutPercent)]
  ]
  if (topic === 'funnel') {
    const extra: [string, string][] = []
    if (summary.opens !== null)
      extra.push(['Переходы в карточки', formatNumber(summary.opens)])
    if (summary.carts !== null)
      extra.push(['Добавления в корзину', formatNumber(summary.carts)])
    if (summary.wishlist !== null)
      extra.push(['Добавления в избранное', formatNumber(summary.wishlist)])
    if (summary.cartPercent !== null)
      extra.push(['Конверсия в корзину', formatPercent(summary.cartPercent)])
    if (summary.orderPercent !== null)
      extra.push([
        'Конверсия из корзины в заказ',
        formatPercent(summary.orderPercent)
      ])
    rows.unshift(...extra)
  }
  return (
    <View style={styles.values}>
      {rows.map(([title, value]) => (
        <View
          key={title}
          style={styles.value}
        >
          <View style={styles.label}>
            <Text
              tone='secondary'
              style={styles.labelText}
            >
              {title}
            </Text>
            {title === 'Выкуплено' && <BuyoutHint />}
          </View>
          <Text
            variant='bodyStrong'
            tabular
          >
            {value}
          </Text>
        </View>
      ))}
    </View>
  )
}

const useStyles = createStyles(({ spacing }) => ({
  heading: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  title: { flex: 1 },
  detail: { marginTop: spacing.huge },
  sections: { gap: spacing.lg },
  values: { paddingVertical: spacing.sm, gap: spacing.sm },
  value: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: spacing.md
  },
  label: { flex: 1, flexDirection: 'row', alignItems: 'center', minWidth: 0 },
  labelText: { flexShrink: 1 }
}))
