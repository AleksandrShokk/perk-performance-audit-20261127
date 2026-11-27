'use client'

import { formatUnits } from '@app/analytics/format'
import { useState } from 'react'

import type { InventoryPosition } from '@app/api'

import { Empty } from '@/components/feedback'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog'

import { CopyValue } from '@/features/products/components/copy-value'
import { ProductGallery } from '@/features/products/components/product-gallery'
import {
  platformName,
  sizeLabel,
  variantKey
} from '@/features/products/model/catalog'

import {
  fbsVariantUnits,
  positionMarketplace,
  stockBasisTitle,
  stockCover,
  warehouseLines
} from '../model/stock'

import { StockChannel } from './stock-summary'

export function StockDetails({
  position,
  currency,
  canCost,
  onClose
}: {
  position: InventoryPosition
  currency: string
  canCost: boolean
  onClose: () => void
}) {
  const [tab, setTab] = useState<'sizes' | 'fbo' | 'fbs'>('sizes')
  const [size, setSize] = useState('all')
  const product = position.product
  const variants = product.variants.filter(
    variant => size === 'all' || variantKey(variant) === size
  )
  const warehouses = warehouseLines(position, size).filter(
    row => row.channel.toLowerCase() === tab
  )
  return (
    <Dialog
      open
      onOpenChange={open => {
        if (!open) onClose()
      }}
    >
      <DialogContent className='product-dialog stock-dialog'>
        <DialogHeader>
          <DialogTitle>{product.title}</DialogTitle>
          <DialogDescription>
            {product.store_name} · {platformName(positionMarketplace(position))}
          </DialogDescription>
        </DialogHeader>
        <div className='product-dialog-scroll'>
          <div className='stock-details-grid'>
            <ProductGallery
              photos={product.photos ?? []}
              title={product.title}
            />
            <div className='product-information'>
              <div className='product-meta-heading'>
                <span>{product.brand}</span>
                <span>{product.colors.join(', ')}</span>
              </div>
              <div className='product-identifiers'>
                <div>
                  <span>Артикул продавца</span>
                  <CopyValue
                    value={product.vendor_code || '—'}
                    label='артикул продавца'
                  />
                </div>
                <div>
                  <span>{platformName(positionMarketplace(position))}</span>
                  <CopyValue
                    value={
                      product.marketplace_code ||
                      product.nm_id ||
                      product.external_id ||
                      '—'
                    }
                    label='артикул площадки'
                  />
                </div>
              </div>
              <div className='stock-details-summary'>
                <StockChannel
                  title='FBO'
                  amount={position.fbo}
                  currency={currency}
                  canCost={canCost}
                />
                <StockChannel
                  title='FBS'
                  amount={position.fbs}
                  currency={currency}
                  canCost={canCost}
                />
              </div>
              <div className='stock-position-cover'>
                <span>{stockBasisTitle(position.turnover_basis)}</span>
                <strong>
                  {stockCover(position.turnover_days, position.turnover_status)}
                </strong>
              </div>
              <div className='stock-detail-toolbar'>
                <div
                  className='stock-switch'
                  role='tablist'
                  aria-label='Детализация остатков'
                >
                  {(['sizes', 'fbo', 'fbs'] as const).map(value => (
                    <button
                      key={value}
                      role='tab'
                      id={`stock-${value}-tab`}
                      aria-selected={tab === value}
                      aria-controls='stock-detail-panel'
                      tabIndex={tab === value ? 0 : -1}
                      onClick={() => setTab(value)}
                      onKeyDown={event => {
                        if (
                          event.key === 'ArrowLeft' ||
                          event.key === 'ArrowRight'
                        ) {
                          event.preventDefault()
                          const next =
                            value === 'sizes'
                              ? 'fbo'
                              : value === 'fbo'
                                ? 'fbs'
                                : 'sizes'
                          setTab(next)
                          document.getElementById(`stock-${next}-tab`)?.focus()
                        }
                      }}
                    >
                      {value === 'sizes'
                        ? 'По размерам'
                        : value === 'fbo'
                          ? 'Склады площадки'
                          : 'Склады продавца'}
                    </button>
                  ))}
                </div>
                {product.variants.length > 1 && (
                  <select
                    className='native-select'
                    aria-label='Размер в детализации'
                    value={size}
                    onChange={event => setSize(event.target.value)}
                  >
                    <option value='all'>Все размеры</option>
                    {product.variants.map(variant => (
                      <option
                        key={variantKey(variant)}
                        value={variantKey(variant)}
                      >
                        {sizeLabel(variant)}
                      </option>
                    ))}
                  </select>
                )}
              </div>
              <div
                role='tabpanel'
                id='stock-detail-panel'
                aria-labelledby={`stock-${tab}-tab`}
                className='stock-detail-table'
              >
                {tab === 'sizes' ? (
                  variants.length ? (
                    <table>
                      <thead>
                        <tr>
                          <th>Размер</th>
                          <th>Штрихкод</th>
                          <th>FBO</th>
                          <th>FBS</th>
                        </tr>
                      </thead>
                      <tbody>
                        {variants.map(variant => (
                          <tr key={variantKey(variant)}>
                            <td>{sizeLabel(variant)}</td>
                            <td>
                              {variant.barcodes.length
                                ? variant.barcodes.map(code => (
                                    <CopyValue
                                      key={code}
                                      value={code}
                                      label={`штрихкод ${code}`}
                                    />
                                  ))
                                : '—'}
                            </td>
                            <td>{formatUnits(variant.stock)}</td>
                            <td>
                              {formatUnits(fbsVariantUnits(position, variant))}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  ) : (
                    <Empty title='Нет разбивки по размерам' />
                  )
                ) : warehouses.length ? (
                  <table>
                    <thead>
                      <tr>
                        <th>Склад</th>
                        <th>Схема</th>
                        <th>Размер</th>
                        <th>Остаток</th>
                      </tr>
                    </thead>
                    <tbody>
                      {warehouses.map(row => (
                        <tr key={row.key}>
                          <td>{row.name}</td>
                          <td>{row.channel}</td>
                          <td>{sizeLabel(row.variant)}</td>
                          <td>{formatUnits(row.quantity)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <Empty title='Нет разбивки по складам' />
                )}
              </div>
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
