import { formatNumber, formatUnits } from '@app/analytics/format'
import type { ReactNode } from 'react'

import type {
  ReplenishmentItem,
  ReplenishmentOverview,
  SupplyCard
} from '@app/api'

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog'

import { CopyValue } from '@/features/products/components/copy-value'
import { ProductGallery } from '@/features/products/components/product-gallery'
import { platformName } from '@/features/products/model/catalog'

import {
  recommendationPlatform,
  supplyDate,
  supplyNumber,
  supplyStatus
} from '../model/supplies'

function Value({
  label,
  children,
  accent = false
}: {
  label: string
  children: ReactNode
  accent?: boolean
}) {
  return (
    <div className={`supply-detail-value ${accent ? 'accent' : ''}`}>
      <span>{label}</span>
      <strong>{children}</strong>
    </div>
  )
}
export function RecommendationDetails({
  item,
  summary,
  onClose
}: {
  item: ReplenishmentItem
  summary?: ReplenishmentOverview
  onClose: () => void
}) {
  const code = item.marketplace_code || item.nm_id
  return (
    <Dialog
      open
      onOpenChange={open => {
        if (!open) onClose()
      }}
    >
      <DialogContent className='product-dialog supply-recommendation-dialog'>
        <DialogHeader>
          <DialogTitle>{item.title}</DialogTitle>
          <DialogDescription>
            {item.store_name} · {platformName(recommendationPlatform(item))}
          </DialogDescription>
        </DialogHeader>
        <div className='product-dialog-scroll'>
          <div className='supply-details-grid'>
            <ProductGallery
              photos={item.photo ? [item.photo] : []}
              title={item.title}
            />
            <div className='supply-detail-content'>
              {!!item.colors.length && (
                <p className='muted'>{item.colors.join(', ')}</p>
              )}
              <div className='product-identifiers'>
                <div>
                  <span>Артикул продавца</span>
                  <CopyValue
                    value={item.vendor_code || '—'}
                    label='артикул продавца'
                  />
                </div>
                <div>
                  <span>{platformName(recommendationPlatform(item))}</span>
                  <CopyValue
                    value={code || '—'}
                    label='артикул площадки'
                  />
                </div>
                {item.barcodes.map(code => (
                  <div key={code}>
                    <span>Штрихкод</span>
                    <CopyValue
                      value={code}
                      label={`штрихкод ${code}`}
                    />
                  </div>
                ))}
              </div>
              <Value
                label='Рекомендуем довезти'
                accent
              >
                {formatUnits(item.quantity)}
              </Value>
              <Value label='В коробе'>
                {formatUnits(item.box_multiple ?? 1)}
              </Value>
              <Value label='Остаток FBO'>{formatUnits(item.stock)}</Value>
              {summary?.include_fbs && (
                <Value label='Зачтено из FBS'>
                  {formatUnits(item.fbs_reduction)}
                </Value>
              )}
              <Value label='В оформленных поставках'>
                {formatUnits(item.incoming_quantity)}
              </Value>
              {!!item.incoming_reduction && (
                <Value label='Снижение потребности'>
                  {formatUnits(item.incoming_reduction)}
                </Value>
              )}
              <Value
                label={
                  item.demand_basis === 'ozon_sales'
                    ? 'Продаж в день'
                    : 'Заказов в день'
                }
              >
                {formatNumber(item.daily_orders, 1)}
              </Value>
              <Value label='Запас сейчас'>
                {formatNumber(item.days_of_stock, 1)} дн.
              </Value>
              <Value label='Запас после поступления'>
                {summary?.target_days ?? 30} дней
              </Value>
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
export function PlacedSupplyDetails({
  item,
  onClose
}: {
  item: SupplyCard
  onClose: () => void
}) {
  return (
    <Dialog
      open
      onOpenChange={open => {
        if (!open) onClose()
      }}
    >
      <DialogContent className='supply-placed-dialog'>
        <DialogHeader>
          <DialogTitle>{supplyNumber(item)}</DialogTitle>
          <DialogDescription>
            {item.store_name} ·{' '}
            {platformName(item.marketplace ?? 'wildberries')}
          </DialogDescription>
        </DialogHeader>
        <div className='supply-placed-content'>
          <Value
            label='Статус'
            accent
          >
            {supplyStatus(item)}
          </Value>
          <Value label='Номер'>
            <CopyValue
              value={
                item.display_number ||
                item.supply_id ||
                item.preorder_id ||
                item.external_id
              }
              label='номер поставки'
            />
          </Value>
          <Value label='В поставке'>{formatUnits(item.quantity)}</Value>
          <Value label='Принято'>{formatUnits(item.accepted_quantity)}</Value>
          <Value label='Плановая дата'>{supplyDate(item.planned_date)}</Value>
          {item.actual_date && (
            <Value label='Фактическая дата'>
              {supplyDate(item.actual_date)}
            </Value>
          )}
          {item.created_date && (
            <Value label='Дата оформления'>
              {supplyDate(item.created_date)}
            </Value>
          )}
          <Value label='Склад / кластер'>{item.destination || '—'}</Value>
        </div>
      </DialogContent>
    </Dialog>
  )
}
