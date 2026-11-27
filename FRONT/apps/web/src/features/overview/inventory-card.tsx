'use client'

import { formatMoney, formatNumber, formatUnits } from '@app/analytics/format'
import { ArrowUpRight, Package } from 'lucide-react'
import Image from 'next/image'
import { useState } from 'react'

import {
  type InventoryAmounts,
  type InventoryPosition,
  inventoryOverview
} from '@app/api'

import { PagedDialog } from '@/components/paged-dialog'
import { Button } from '@/components/ui/button'

import { useAuth } from '@/features/auth/auth-provider'
import { CoverageControl } from '@/features/inventory/components/coverage-control'
import { useCoverageChannel } from '@/features/inventory/hooks/use-coverage-channel'
import { useWorkspace } from '@/features/workspace/workspace-provider'

import type { Overview } from './use-overview'

export function InventoryCard({ overview }: { overview: Overview }) {
  const [open, setOpen] = useState(false)
  const scope = useWorkspace()
  const [coverage_channel] = useCoverageChannel()
  const { user } = useAuth()
  const value = overview.inventory.data
  return (
    <section
      className='surface inventory-card'
      id='inventory'
      aria-labelledby='inventory-title'
    >
      <div className='section-heading'>
        <div className='icon-heading'>
          <span className='square-icon'>
            <Package size={19} />
          </span>
          <h2 id='inventory-title'>Остатки</h2>
        </div>
        <CoverageControl />
      </div>
      <div className='inventory-columns'>
        <StockAmounts
          title='FBO'
          value={value?.fbo}
          currency={value?.currency}
        />
        <StockAmounts
          title='FBS'
          value={value?.fbs}
          currency={value?.currency}
        />
      </div>
      <div className='stock-footer'>
        <div>
          <span className='muted'>Запас в днях</span>
          <strong>
            {value?.turnover_days != null
              ? `${formatNumber(value.turnover_days, 1)} дн.`
              : '—'}
          </strong>
        </div>
        {value?.can_cost && (
          <div>
            <span className='muted'>
              {value.total.cost_complete
                ? 'Стоимость по себестоимости'
                : 'Себестоимость · известная часть'}
            </span>
            <strong>
              {formatMoney(value.total.cost_value, value.currency)}
            </strong>
          </div>
        )}
      </div>
      <Button
        className='section-button'
        variant='ghost'
        disabled={!scope.workspace}
        onClick={() => setOpen(true)}
      >
        Остатки по товарам
        <ArrowUpRight size={16} />
      </Button>
      <PagedDialog<InventoryPosition>
        open={open}
        onClose={() => setOpen(false)}
        title='Остатки по товарам'
        description='Товары в наличии на FBO и FBS.'
        queryKey={[
          'user',
          user?.id,
          scope.accessKey,
          coverage_channel,
          scope.store?.id,
          'inventory-list'
        ]}
        load={(offset, signal) =>
          inventoryOverview(
            scope.workspace!.id,
            {
              coverage_channel,
              store_id: scope.store?.id,
              in_stock: true,
              limit: 30,
              offset
            },
            { signal }
          )
        }
        rowKey={row =>
          `${row.product.store_id}:${row.product.id ?? row.product.nm_id}`
        }
        render={row => (
          <>
            <ProductLabel
              title={row.product.title}
              article={row.product.vendor_code || row.product.marketplace_code}
              photo={row.product.photos?.[0]}
            />
            <div className='row-stock'>
              <span>
                FBO <b>{formatUnits(row.fbo.units)}</b>
              </span>
              <span>
                FBS <b>{formatUnits(row.fbs.units)}</b>
              </span>
              <span>
                Запас{' '}
                <b>
                  {row.turnover_days != null
                    ? `${formatNumber(row.turnover_days, 1)} дн.`
                    : row.turnover_status === 'no_orders'
                      ? 'Нет заказов'
                      : '—'}
                </b>
              </span>
            </div>
          </>
        )}
      />
    </section>
  )
}
function StockAmounts({
  title,
  value,
  currency
}: {
  title: string
  value?: InventoryAmounts
  currency?: string
}) {
  return (
    <div className='stock-amounts'>
      <span className='channel-tag'>{title}</span>
      <strong>{formatUnits(value?.units)}</strong>
      <span>{formatMoney(value?.retail_value, currency)}</span>
    </div>
  )
}
export function ProductLabel({
  title,
  article,
  photo
}: {
  title: string
  article?: string
  photo?: string | null
}) {
  return (
    <div className='product-label'>
      {photo ? (
        <Image
          src={photo}
          alt=''
          width={42}
          height={54}
          unoptimized
          className='product-photo'
        />
      ) : (
        <span className='product-photo placeholder'>
          <Package size={20} />
        </span>
      )}
      <span>
        <strong>{title}</strong>
        <small>{article || '—'}</small>
      </span>
    </div>
  )
}
