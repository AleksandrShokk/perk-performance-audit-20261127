'use client'
import { ChoiceSelect } from '@/components/choice-select'

import { useCoverageChannel } from '../hooks/use-coverage-channel'

export function CoverageControl() {
  const [channel, set] = useCoverageChannel()
  return (
    <ChoiceSelect
      label='Схема для расчёта запаса'
      value={channel}
      onChange={set}
      options={[
        { value: 'fbo', label: 'Запас FBO' },
        { value: 'fbs', label: 'Запас FBS' },
        { value: 'all', label: 'Запас FBO + FBS' }
      ]}
    />
  )
}
