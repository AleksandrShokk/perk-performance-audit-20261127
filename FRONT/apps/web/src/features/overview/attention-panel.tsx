import { formatMoney, formatNumber } from '@app/analytics/format'
import { ArrowUpRight, PackageOpen, Truck, Warehouse } from 'lucide-react'

import { useWorkspace } from '@/features/workspace/workspace-provider'

import type { TableTab } from './overview-table'
import type { Overview } from './use-overview'

export function AttentionPanel({
  overview,
  onTab
}: {
  overview: Overview
  onTab: (tab: TableTab) => void
}) {
  const scope = useWorkspace()
  const rec = overview.replenishment.data
  const supplies = overview.supplies.data
  const upcoming =
    supplies?.items.filter(
      item => !['accepted', 'cancelled'].includes(item.status)
    ) ?? []
  return (
    <aside
      className='surface attention-panel'
      aria-labelledby='attention-title'
    >
      <h2 id='attention-title'>Требуют внимания</h2>
      <button
        className='attention-item'
        onClick={() => onTab('supplies')}
      >
        <span className='attention-symbol'>
          <PackageOpen size={20} />
        </span>
        <span>
          <span>Заканчиваются</span>
          <strong>
            {formatNumber(rec?.urgent_count)} <small>позиций</small>
          </strong>
        </span>
        <ArrowUpRight size={16} />
      </button>
      <button
        className='attention-item'
        onClick={() => onTab('supplies')}
      >
        <span className='attention-symbol'>
          <Truck size={20} />
        </span>
        <span>
          <span>Поставить на {rec?.target_days ?? 30} дней</span>
          <strong>
            {formatNumber(rec?.recommended_units)} <small>шт.</small>
          </strong>
        </span>
        <ArrowUpRight size={16} />
      </button>
      <div className='attention-upcoming'>
        <span className='muted'>Поставки в работе</span>
        {upcoming.length ? (
          upcoming.slice(0, 2).map(item => (
            <button
              key={`${item.store_id}:${item.external_id}`}
              onClick={() => onTab('supplies')}
            >
              <span>
                <strong>{item.display_number ?? item.external_id}</strong>
                <small>{item.destination || item.store_name}</small>
              </span>
              <span>
                {formatNumber(item.quantity)} <small>шт.</small>
              </span>
            </button>
          ))
        ) : (
          <p className='muted'>
            {supplies?.loading ? 'Загружаем…' : 'Нет активных поставок'}
          </p>
        )}
      </div>
      {scope.can('finance.read') && (
        <a
          className='storage-link'
          href='#finance'
        >
          <Warehouse size={17} />
          <span>Хранение · 30 дней</span>
          <strong>
            {formatMoney(overview.storage, overview.finance.data?.currency)}
          </strong>
        </a>
      )}
    </aside>
  )
}
