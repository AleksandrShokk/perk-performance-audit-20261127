'use client'

import { formatNumber } from '@app/analytics/format'
import { useState } from 'react'

import type { ProductModel } from '@app/api'

import { ChoiceSelect } from '@/components/choice-select'
import { Empty } from '@/components/feedback'
import { ProductLabel } from '@/components/product-label'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog'

import { useWorkspace } from '@/features/workspace/workspace-provider'

import {
  platformName,
  productKey,
  productOptions,
  sizeLabel,
  variantKey
} from '../model/catalog'

import { CopyValue } from './copy-value'
import { ProductGallery } from './product-gallery'
import { VariantCosts } from './variant-costs'

export type ProductSelection = {
  id: string
  model: ProductModel
  initialProduct?: string
}
export function ProductDetails({
  model,
  initialProduct,
  currency,
  onClose,
  onGrouping,
  onSaved
}: {
  model: ProductModel
  initialProduct?: string
  currency: string
  onClose: () => void
  onGrouping?: () => void
  onSaved: () => void
}) {
  const scope = useWorkspace()
  const [selected, setSelected] = useState(
    initialProduct ?? (model.products[0] ? productKey(model.products[0]) : '')
  )
  const product =
    model.products.find(item => productKey(item) === selected) ??
    model.products[0]
  const [size, setSize] = useState('')
  const variant =
    product?.variants.find(item => variantKey(item) === size) ??
    product?.variants[0]
  const storeProducts = model.products.filter(
    item => item.store_id === product?.store_id
  )
  const options =
    product?.marketplace === 'ozon'
      ? [
          ...new Map(
            storeProducts.map(item => [
              item.colors
                .map(c => c.trim().toLocaleLowerCase())
                .sort()
                .join('|'),
              item
            ])
          ).entries()
        ].map(([key, item]) => ({
          product: item,
          label: item.colors.join(', ') || 'Все цвета',
          key
        }))
      : productOptions(storeProducts).map(item => ({
          ...item,
          key: productKey(item.product)
        }))
  const colorKey = (item: typeof product) =>
    item?.colors
      .map(c => c.trim().toLocaleLowerCase())
      .sort()
      .join('|') ?? ''
  const sizeProducts =
    product?.marketplace === 'ozon'
      ? storeProducts.filter(item => colorKey(item) === colorKey(product))
      : product
        ? [product]
        : []
  const sizes = sizeProducts
    .flatMap(card => card.variants.map(item => ({ card, item })))
    .sort((a, b) =>
      sizeLabel(a.item).localeCompare(sizeLabel(b.item), 'ru', {
        numeric: true
      })
    )
  return (
    <Dialog
      open
      onOpenChange={open => {
        if (!open) onClose()
      }}
    >
      <DialogContent className='product-dialog'>
        <DialogHeader>
          <DialogTitle>{model.title}</DialogTitle>
          <DialogDescription>
            {model.store_name} · {platformName(model.marketplace)}
          </DialogDescription>
        </DialogHeader>
        {!product ? (
          <Empty title='Карточка обновляется' />
        ) : (
          <div className='product-dialog-scroll'>
            <div className='product-details-grid'>
              <ProductGallery
                key={productKey(product)}
                photos={product.photos ?? []}
                title={product.title}
              />
              <div className='product-information'>
                {model.combined && (
                  <ChoiceSelect
                    label='Кабинет товара'
                    value={product.store_id}
                    options={[
                      ...new Map(
                        model.products.map(item => [
                          item.store_id,
                          {
                            value: item.store_id,
                            label: `${item.store_name} · ${platformName(item.marketplace)}`
                          }
                        ])
                      ).values()
                    ]}
                    onChange={value => {
                      const next = model.products.find(
                        item => item.store_id === value
                      )
                      if (next) setSelected(productKey(next))
                      setSize('')
                    }}
                  />
                )}

                {scope.admin && onGrouping && (
                  <Button
                    variant='outline'
                    onClick={onGrouping}
                  >
                    Настроить объединение
                  </Button>
                )}
                <div className='product-meta-heading'>
                  <span>{product.brand || model.brand}</span>
                  <span>{product.subject}</span>
                </div>
                {product.title !== model.title && (
                  <h3 className='selected-product-title'>{product.title}</h3>
                )}
                {options.length > 1 && (
                  <div className='product-option-section'>
                    <h3>Цвет</h3>
                    <div
                      className='product-color-options'
                      role='group'
                      aria-label='Вариант карточки'
                    >
                      {options.map(({ product: item, label, key }) => (
                        <button
                          key={key}
                          aria-pressed={
                            product?.marketplace === 'ozon'
                              ? colorKey(item) === colorKey(product)
                              : productKey(item) === productKey(product)
                          }
                          aria-label={`Выбрать ${label}`}
                          onClick={() => {
                            setSelected(productKey(item))
                            setSize('')
                          }}
                        >
                          <ProductLabel
                            title={label}
                            photo={item.photos?.[0]}
                          />
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                {(sizes.length > 1 ||
                  (variant?.size && variant.size !== '0')) && (
                  <div className='product-option-section'>
                    <h3>Размер</h3>
                    <div
                      className='product-size-options'
                      role='group'
                      aria-label='Размер товара'
                    >
                      {sizes.map(({ card, item }) => (
                        <button
                          key={`${productKey(card)}:${variantKey(item)}`}
                          aria-pressed={
                            !!variant &&
                            variantKey(item) === variantKey(variant)
                          }
                          aria-label={`Размер ${sizeLabel(item)}`}
                          onClick={() => {
                            setSelected(productKey(card))
                            setSize(variantKey(item))
                          }}
                        >
                          {sizeLabel(item)}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                <div className='product-identifiers'>
                  <div>
                    <span>Артикул продавца</span>
                    <CopyValue
                      key={`seller:${productKey(product)}`}
                      value={product.vendor_code || '—'}
                      label='артикул продавца'
                    />
                  </div>
                  <div>
                    <span>{platformName(product.marketplace)}</span>
                    <CopyValue
                      key={`native:${productKey(product)}`}
                      value={
                        product.marketplace_code ||
                        product.nm_id ||
                        product.external_id ||
                        '—'
                      }
                      label='артикул площадки'
                    />
                  </div>
                  {variant?.barcodes.map(code => (
                    <div key={code}>
                      <span>Штрихкод</span>
                      <CopyValue
                        value={code}
                        label={`штрихкод ${code}`}
                      />
                    </div>
                  ))}
                </div>
                {scope.can('inventory.read') && (
                  <>
                    <div className='product-stock-summary'>
                      <div>
                        <span>FBO</span>
                        <strong>
                          {formatNumber(
                            variant ? variant.stock : product.stock
                          )}{' '}
                          <small>шт.</small>
                        </strong>
                      </div>
                      <div>
                        <span>К покупателю</span>
                        <strong>
                          {formatNumber(variant?.to_client)} <small>шт.</small>
                        </strong>
                      </div>
                      <div>
                        <span>Возвращается</span>
                        <strong>
                          {formatNumber(variant?.from_client)}{' '}
                          <small>шт.</small>
                        </strong>
                      </div>
                    </div>
                    {!!variant?.warehouses.length && (
                      <details className='product-warehouses'>
                        <summary>По складам</summary>
                        {variant.warehouses.map((warehouse, i) => (
                          <div key={`${warehouse.name}:${i}`}>
                            <span>{warehouse.name}</span>
                            <strong>
                              {formatNumber(warehouse.quantity)} шт.
                            </strong>
                          </div>
                        ))}
                      </details>
                    )}
                  </>
                )}
                {scope.can('profit.read') && (
                  <VariantCosts
                    key={`${productKey(product)}:${variant ? variantKey(variant) : 'all'}`}
                    product={product}
                    variant={variant}
                    workspaceId={scope.workspace!.id}
                    marketplace={product.marketplace ?? 'wildberries'}
                    currency={currency}
                    onSaved={onSaved}
                  />
                )}
              </div>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
