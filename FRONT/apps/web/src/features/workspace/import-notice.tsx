import { initialImportMessage } from '@app/analytics/onboarding'
import { Info, X } from 'lucide-react'

import { Button } from '@/components/ui/button'

import { useWorkspace } from './workspace-provider'

export function ImportNotice() {
  const scope = useWorkspace()
  if (!scope.importNotice) return null
  return (
    <div
      role='status'
      className='surface mb-5 flex items-start gap-3 border border-primary/30 bg-primary/10 p-4'
    >
      <Info
        size={19}
        className='mt-0.5 shrink-0 text-primary'
      />
      <div className='flex-1'>
        <strong>{scope.importNotice}: загрузка началась</strong>
        <p className='mt-1 text-sm text-muted-foreground'>
          {initialImportMessage}
        </p>
      </div>
      <Button
        variant='ghost'
        size='icon'
        aria-label='Закрыть сообщение о загрузке'
        onClick={scope.dismissImportNotice}
      >
        <X size={16} />
      </Button>
    </div>
  )
}
