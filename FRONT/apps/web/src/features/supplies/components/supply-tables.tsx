import { formatNumber, formatUnits } from '@app/analytics/format'

import type {
  ReplenishmentItem,
  ReplenishmentOverview,
  SupplyCard,
  SupplyList
} from '@app/api'

import { ProductLabel } from '@/components/product-label'

import {
  type IdentifierMode,
  platformName
} from '@/features/products/model/catalog'

import {
  recommendationArticle,
  recommendationKey,
  recommendationPlatform,
  supplyDate,
  supplyKey,
  supplyNumber,
  supplyStatus
} from '../model/supplies'

import { SupplyPagination } from './supply-pagination'

type Pagination = {
  page: number
  busy: boolean
  onPage: (page: number) => void
}
export function RecommendationsTable({
  data,
  mode,
  page,
  busy,
  onPage,
  onOpen,
  onPackaging
}: Pagination & {
  data: ReplenishmentOverview
  mode: IdentifierMode
  onOpen: (item: ReplenishmentItem) => void
  onPackaging?: (item: ReplenishmentItem) => void
}) {
  return (
    <section
      className='surface supply-table'
      aria-label='Рекомендации к поставке'
    >
      <div className='supply-table-scroll'>
        <table className='supply-data'>
          <thead>
            <tr>
              <th>Товар</th>
              <th className='supply-store'>Кабинет</th>
              <th>Остаток FBO</th>
              <th>В поставках</th>
              <th>Запас, дней</th>
              <th>В коробе, шт.</th>
              <th>Довезти</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map(item => (
              <tr key={recommendationKey(item)}>
                <td>
                  <button
                    className='supply-product-button'
                    aria-label={`Рекомендация ${item.title} · ${item.vendor_code || item.marketplace_code || item.nm_id}`}
                    onClick={() => onOpen(item)}
                  >
                    <ProductLabel
                      title={item.title}
                      article={recommendationArticle(item, mode)}
                      photo={item.photo}
                    />
                    <small className='supply-mobile-store'>
                      {item.store_name} ·{' '}
                      {platformName(recommendationPlatform(item))}
                    </small>
                  </button>
                </td>
                <td className='supply-store'>
                  <span>{item.store_name}</span>
                  <small>{platformName(recommendationPlatform(item))}</small>
                </td>
                <td className='supply-numeric'>{formatUnits(item.stock)}</td>
                <td className='supply-numeric'>
                  {formatUnits(item.incoming_quantity)}
                </td>
                <td className='supply-numeric'>
                  {formatNumber(item.days_of_stock, 1)}
                  {item.urgent && (
                    <span
                      className='supply-urgent-dot'
                      role='img'
                      aria-label='Срочная позиция'
                    />
                  )}
                </td>
                <td className='supply-numeric'>
                  {onPackaging ? (
                    <button
                      className='supply-packaging-button'
                      aria-label={
                        'Кратность ' +
                        item.title +
                        ' · ' +
                        (item.vendor_code ||
                          item.marketplace_code ||
                          item.nm_id)
                      }
                      onClick={() => onPackaging(item)}
                    >
                      {formatNumber(item.box_multiple ?? 1)}
                    </button>
                  ) : (
                    formatNumber(item.box_multiple ?? 1)
                  )}
                </td>
                <td className='supply-quantity'>
                  {formatUnits(item.quantity)}
                </td>
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
export function PlacedSuppliesTable({
  data,
  page,
  busy,
  onPage,
  onOpen
}: Pagination & { data: SupplyList; onOpen: (item: SupplyCard) => void }) {
  return (
    <section
      className='surface supply-table'
      aria-label='Оформленные поставки'
    >
      <div className='supply-table-scroll'>
        <table className='supply-data supply-history-data'>
          <thead>
            <tr>
              <th>Поставка</th>
              <th className='supply-store'>Кабинет</th>
              <th>Статус</th>
              <th>Склад / кластер</th>
              <th>Плановая дата</th>
              <th>Товаров</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map(item => (
              <tr key={supplyKey(item)}>
                <td>
                  <button
                    className='supply-number-button'
                    onClick={() => onOpen(item)}
                    aria-label={`Открыть ${supplyNumber(item)}`}
                  >
                    {supplyNumber(item)}
                    <small className='supply-mobile-store'>
                      {item.store_name} ·{' '}
                      {platformName(item.marketplace ?? 'wildberries')}
                    </small>
                  </button>
                </td>
                <td className='supply-store'>
                  <span>{item.store_name}</span>
                  <small>
                    {platformName(item.marketplace ?? 'wildberries')}
                  </small>
                </td>
                <td>
                  <span
                    className={`supply-status ${item.rejected ? 'rejected' : item.status}`}
                  >
                    {supplyStatus(item)}
                  </span>
                </td>
                <td>{item.destination || '—'}</td>
                <td className='supply-date'>{supplyDate(item.planned_date)}</td>
                <td className='supply-numeric'>{formatUnits(item.quantity)}</td>
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
