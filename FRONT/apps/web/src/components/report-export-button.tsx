'use client'

import { Download } from 'lucide-react'

import { ErrorNotice } from '@/components/feedback'
import { Button } from '@/components/ui/button'

import { useProtectedAction } from '@/hooks/use-protected-action'

import { downloadFile, downloadResponse } from '@/lib/download'

export function ReportExportButton({
  request,
  filename,
  label,
  disabled = false
}: {
  request: (signal: AbortSignal) => Promise<Blob>
  filename: string
  label: string
  disabled?: boolean
}) {
  const download = useProtectedAction(
    async signal => ({
      file: await downloadResponse(request(signal)),
      name: filename
    }),
    result => downloadFile(result.file, result.name),
    { refresh: false }
  )
  return (
    <div className='catalog-heading-actions'>
      <Button
        variant='outline'
        disabled={disabled || download.isPending}
        onClick={() => download.mutate()}
      >
        <Download size={15} />
        {download.isPending ? 'Готовим файл…' : label}
      </Button>
      <ErrorNotice error={download.error} />
    </div>
  )
}
