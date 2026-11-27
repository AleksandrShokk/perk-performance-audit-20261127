import { router } from 'expo-router'

import { Button, Card, Notice, Text } from '@/components/ui'

import { useWorkspace } from '@/features/workspace/providers/WorkspaceProvider'

import { errorMessage } from '@/lib/errors'
import { formatNumber } from '@/lib/format'

import { useCatalogSync } from '../hooks/useCatalogSync'

import { createStyles } from '@/theme'

export function OzonCatalogStatus({
  workspaceId,
  storeId
}: {
  workspaceId: string
  storeId: string
}) {
  const styles = useStyles()
  const { selectStore } = useWorkspace()
  const { status, refresh } = useCatalogSync(workspaceId, storeId)
  const data = status.data
  const loading =
    !!data && ['pending', 'queued', 'running'].includes(data.status)
  return (
    <Card style={styles.content}>
      <Text variant='sectionTitle'>Каталог и остатки</Text>
      <Text tone='secondary'>
        {loading
          ? `Загружаем… ${data.records_processed ? formatNumber(data.records_processed) + ' товаров' : ''}`
          : data?.status === 'ready'
            ? `${formatNumber(data.records_processed)} товаров · обновляется в фоне`
            : data?.status === 'error'
              ? 'Не удалось обновить данные'
              : 'Проверяем загрузку…'}
      </Text>
      {(status.error || refresh.error) && (
        <Notice
          tone='error'
          message={errorMessage(status.error ?? refresh.error)}
        />
      )}
      {data?.error_code && (
        <Notice
          tone='error'
          message={
            data.error_code === 'ozon_access_denied'
              ? 'У ключа нет доступа к каталогу, остаткам или ценам. Проверьте права ключа.'
              : 'Обновление повторится автоматически. Предыдущие данные сохранены.'
          }
        />
      )}
      <Button
        title='Открыть товары'
        variant='secondary'
        disabled={!data?.updated_at}
        onPress={() => {
          selectStore(storeId)
          router.push('/(tabs)/products')
        }}
      />
      <Button
        title='Обновить данные'
        variant='ghost'
        loading={refresh.isPending}
        disabled={loading}
        onPress={() => refresh.mutate()}
      />
    </Card>
  )
}
const useStyles = createStyles(({ spacing }) => ({
  content: { gap: spacing.sm }
}))
