import { Info } from 'lucide-react'
import type { ReactNode } from 'react'

import {
  Tooltip,
  TooltipContent,
  TooltipTrigger
} from '@/components/ui/tooltip'

export function ReportHint({
  label,
  children
}: {
  label: string
  children: ReactNode
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          className='icon-hint'
          aria-label={label}
        >
          <Info size={14} />
        </button>
      </TooltipTrigger>
      <TooltipContent className='max-w-80 whitespace-pre-line'>
        {children}
      </TooltipContent>
    </Tooltip>
  )
}
