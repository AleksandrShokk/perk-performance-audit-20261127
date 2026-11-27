import { Notice, Screen } from '@/components/ui'

import { useWorkspace } from '../providers/WorkspaceProvider'

import { StoreSwitcher } from './StoreSwitcher'

export function UpcomingReport() {
  const { allStores } = useWorkspace()
  return (
    <Screen headerCenter={<StoreSwitcher compact />}>
      <Notice
        message={
          allStores
            ? 'Общий отчёт станет доступен после подключения остальных данных Ozon. Пока выберите магазин WB.'
            : 'Для Ozon доступны заказы, товары и остатки. Этот раздел добавим следующим этапом.'
        }
      />
    </Screen>
  )
}
