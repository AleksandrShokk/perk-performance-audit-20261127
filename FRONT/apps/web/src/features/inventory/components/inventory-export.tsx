'use client'

import { inventoryOverviewExport } from '@app/api'

import { ReportExportButton } from '@/components/report-export-button'

import { useWorkspace } from '@/features/workspace/workspace-provider'

import { useCoverageChannel } from '../hooks/use-coverage-channel'

export function InventoryExport({ disabled }: { disabled: boolean }) {
  const scope = useWorkspace()
  const [channel] = useCoverageChannel()
  if (!scope.can('reports.export')) return null
  return (
    <ReportExportButton
      label='Скачать Excel'
      filename='perk-inventory.xlsx'
      disabled={disabled}
      request={signal =>
        inventoryOverviewExport(
          scope.workspace!.id,
          { store_id: scope.store?.id, coverage_channel: channel },
          { signal, responseType: 'blob', timeout: 90000 }
        )
      }
    />
  )
}
