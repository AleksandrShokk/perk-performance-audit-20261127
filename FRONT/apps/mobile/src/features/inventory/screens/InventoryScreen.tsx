import { router } from 'expo-router'
import { Boxes, ChevronRight } from 'lucide-react-native'
import { View } from 'react-native'

import {
  Button,
  Card,
  EmptyState,
  InfoHint,
  Notice,
  Screen,
  Skeleton
} from '@/components/ui'

import { StoreSwitcher } from '@/features/workspace/components/StoreSwitcher'
import { useWorkspace } from '@/features/workspace/providers/WorkspaceProvider'

import { errorMessage } from '@/lib/errors'

import {
  PageHeading,
  ProfileButton
} from '../../../components/navigation/PageHeader'
import { FbsSettingsButton } from '../components/FbsSettingsButton'
import { InventoryTotals } from '../components/InventoryMetrics'
import { useInventoryOverview } from '../hooks/useInventoryOverview'

import { createStyles } from '@/theme'

export default function InventoryScreen() {
  const styles = useStyles()
  const workspace = useWorkspace()
  const query = useInventoryOverview()
  const data = query.data
  const details = [
    'FBO — склады маркетплейса, FBS — склады продавца. Стоимость — текущая цена продавца после его скидки, без скидки маркетплейса.',
    data?.turnover_basis === 'ozon_sales_28d_fbo'
      ? 'Запас FBO в днях получен из Ozon: доступные остатки и среднесуточные продажи за 28 дней. FBS в этот показатель не входит.'
      : 'Запас в днях: текущий остаток / среднесуточные заказы за дни наличия в предыдущие 28 дней.',
    ...(data?.other_channels?.length
      ? [
          'Сводка содержит FBO и FBS. rFBS и FBP пока не входят в эти показатели.'
        ]
      : []),
    ...(data?.can_cost
      ? [
          'Себестоимость показана внутри FBO и FBS. Учитываются позиции с заполненной себестоимостью.'
        ]
      : []),
    ...(data?.turnover_partial
      ? [
          data?.turnover_basis === 'ozon_sales_28d_fbo'
            ? 'Общий запас рассчитан по товарам с доступными данными Ozon.'
            : 'Запас в днях рассчитан по товарам с известными заказами и временем наличия.'
        ]
      : []),
    ...(data && (!data.fbo.retail_complete || !data.fbs.retail_complete)
      ? ['Стоимость рассчитана по позициям с загруженной ценой.']
      : []),
    ...(data?.total.stale || data?.turnover_stale
      ? ['Часть исходных данных ожидает обновления.']
      : [])
  ].join('\n\n')
  return (
    <Screen
      stickyHeader
      bottomInset
      headerCenter={
        workspace.stores.length ? <StoreSwitcher compact /> : undefined
      }
      headerRight={<ProfileButton />}
      onRefresh={() => query.refetch()}
    >
      <View style={styles.sections}>
        <PageHeading title='Остатки'>
          <InfoHint
            title='Остатки'
            message={details}
          />
        </PageHeading>
        {!workspace.can('inventory.read') ? (
          <Notice message='Нет доступа к остаткам.' />
        ) : (
          <>
            {(query.error || workspace.status === 'error') && (
              <Notice
                tone='error'
                message={
                  query.error
                    ? errorMessage(query.error)
                    : 'Не удалось загрузить магазины'
                }
                actionTitle='Повторить'
                onAction={() => {
                  void workspace.refetch()
                  void query.refetch()
                }}
              />
            )}
            {workspace.status === 'ready' && !workspace.stores.length ? (
              <Card>
                <EmptyState
                  icon={Boxes}
                  title='Подключите магазин'
                />
              </Card>
            ) : !data && !query.error ? (
              <Skeleton height={280} />
            ) : (
              data && (
                <>
                  {data.error_code && (
                    <Notice
                      tone='error'
                      message='Не удалось обновить Ozon. Предыдущие данные сохранены; повторим загрузку автоматически.'
                    />
                  )}
                  <InventoryTotals data={data} />
                  <FbsSettingsButton />
                  <Button
                    title='Остатки по товарам'
                    icon={ChevronRight}
                    variant='secondary'
                    block
                    onPress={() => router.push('/inventory/products')}
                  />
                </>
              )
            )}
          </>
        )}
      </View>
    </Screen>
  )
}

const useStyles = createStyles(({ spacing }) => ({
  sections: { gap: spacing.lg }
}))
