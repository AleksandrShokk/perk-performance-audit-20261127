import { cn } from '@/lib/utils'

export function Logo({ className }: { className?: string }) {
  return (
    <span
      className={cn('perk-logo', className)}
      aria-label='PERK'
    >
      <svg
        viewBox='0 0 64 64'
        aria-hidden='true'
      >
        <g
          fill='currentColor'
          transform='rotate(-12 32 32)'
        >
          <rect
            x='8'
            y='8'
            width='21'
            height='21'
            rx='7.5'
          />
          <rect
            x='35'
            y='8'
            width='21'
            height='21'
            rx='7.5'
            opacity='.6'
          />
          <rect
            x='8'
            y='35'
            width='21'
            height='21'
            rx='7.5'
            opacity='.75'
          />
          <rect
            x='35'
            y='35'
            width='21'
            height='21'
            rx='7.5'
          />
        </g>
      </svg>
      <span>PERK</span>
    </span>
  )
}
