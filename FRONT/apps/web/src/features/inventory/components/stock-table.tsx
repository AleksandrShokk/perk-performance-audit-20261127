import { formatUnits } from '@app/analytics/format'
import { ChevronLeft, ChevronRight } from 'lucide-react'

import type { InventoryOverview, InventoryPosition } from '@app/api'

import { ProductLabel } from '@/components/product-label'
import { Button } from '@/components/ui/button'

import { financeMoney } from '@/features/finance/model/finance-format'
import {
  type IdentifierMode,
  identifier,
  platformName
} from '@/features/products/model/catalog'

import { stockPageSize } from '../hooks/use-inventory'
import { positionKey, positionMarketplace, stockCover } from '../model/stock'

export type StockPriceMode = 'retail' | 'cost'
export function StockTable({
  data,
  mode,
  priceMode,
  busy,
  onPage,
  onOpen
}: {
  data: InventoryOverview
  mode: IdentifierMode
  priceMode: StockPriceMode
  busy: boolean
  onPage: (page: number) => void
  onOpen: (position: InventoryPosition) => void
}) {
  const page = Math.floor(data.offset / stockPageSize)
  return (
    <section
      className='surface stock-table'
      aria-label='Остатки по товарам'
    >
      <div className='stock-table-scroll'>
        <table className='stock-data'>
          <thead>
            <tr>
              <th>Товар</th>
              <th className='stock-store'>Кабинет</th>
              <th>FBO</th>
              <th>FBS</th>
              <th>Запас в днях</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map(position => {
              const marketplace = positionMarketplace(position)
              return (
                <tr key={positionKey(position)}>
                  <td>
                    <button
                      className='stock-product-button'
                      aria-label={`Остатки ${position.product.title} · ${position.product.vendor_code || position.product.marketplace_code}`}
                      onClick={() => onOpen(position)}
                    >
                      <ProductLabel
                        title={position.product.title}
                        article={identifier(
                          position.product,
                          mode,
                          marketplace
                        )}
                        photo={position.product.photos?.[0]}
                      />
                      <small className='stock-mobile-store'>
                        {position.product.store_name} ·{' '}
                        {platformName(marketplace)}
                      </small>
                    </button>
                  </td>
                  <td className='stock-store'>
                    <span>{position.product.store_name}</span>
                    <small>{platformName(marketplace)}</small>
                  </td>
                  {(['fbo', 'fbs'] as const).map(channel => (
                    <td
                      key={channel}
                      className='stock-channel-cell'
                    >
                      <strong>{formatUnits(position[channel].units)}</strong>
                      <small>
                        {financeMoney(
                          priceMode === 'cost'
                            ? position[channel].cost_value
                            : position[channel].retail_value,
                          data.currency
                        )}
                      </small>
                    </td>
                  ))}
                  <td className='stock-cover-cell'>
                    {stockCover(
                      position.turnover_days,
                      position.turnover_status
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <div className='table-footer'>
        <span>
          {data.count
            ? `${data.offset + 1}–${Math.min(data.offset + data.limit, data.count)} из ${data.count}`
            : '0 товаров'}
        </span>
        <div>
          <Button
            variant='ghost'
            size='icon-sm'
            aria-label='Предыдущая страница остатков'
            disabled={page === 0 || busy}
            onClick={() => onPage(page - 1)}
          >
            <ChevronLeft size={16} />
          </Button>
          <span>{page + 1}</span>
          <Button
            variant='ghost'
            size='icon-sm'
            aria-label='Следующая страница остатков'
            disabled={data.offset + data.limit >= data.count || busy}
            onClick={() => onPage(page + 1)}
          >
            <ChevronRight size={16} />
          </Button>
        </div>
      </div>
    </section>
  )
}
