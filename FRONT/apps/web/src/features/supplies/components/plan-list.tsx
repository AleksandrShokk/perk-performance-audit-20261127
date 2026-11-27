import { formatNumber, formatUnits } from '@app/analytics/format'

import type { PlanList } from '@app/api'

import { platformName } from '@/features/products/model/catalog'

import { planStatuses } from '../model/plans'
import { supplyDate } from '../model/supplies'

import { SupplyPagination } from './supply-pagination'

export function PlansTable({
  data,
  page,
  busy,
  onPage,
  onOpen
}: {
  data: PlanList
  page: number
  busy: boolean
  onPage: (page: number) => void
  onOpen: (id: string) => void
}) {
  return (
    <section
      className='surface supply-table'
      aria-label='Сохранённые планы'
    >
      <div className='supply-table-scroll'>
        <table className='supply-data'>
          <thead>
            <tr>
              <th>План</th>
              <th>Кабинет</th>
              <th>Склад / кластер</th>
              <th>Статус</th>
              <th>Товаров</th>
              <th>К поставке</th>
              <th>Изменён</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map(plan => (
              <tr key={plan.id}>
                <td>
                  <button
                    className='supply-number-button'
                    onClick={() => onOpen(plan.id)}
                  >
                    {plan.title}
                  </button>
                </td>
                <td>
                  {plan.store_name}
                  <small>{platformName(plan.marketplace)}</small>
                </td>
                <td>{plan.destination || '—'}</td>
                <td>{planStatuses[plan.status]}</td>
                <td className='supply-numeric'>
                  {formatNumber(plan.product_count)}
                </td>
                <td className='supply-quantity'>
                  {formatUnits(plan.quantity)}
                </td>
                <td>{supplyDate(plan.updated_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <SupplyPagination
        page={page}
        count={data.count}
        busy={busy}
        onPage={onPage}
      />
    </section>
  )
}
