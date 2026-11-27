import { formatNumber, formatPercent } from '@app/analytics/format'

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog'

import { financeMoney } from '@/features/finance/model/finance-format'
import { CopyValue } from '@/features/products/components/copy-value'
import { ProductGallery } from '@/features/products/components/product-gallery'
import { platformName } from '@/features/products/model/catalog'

import {
  type AnalyticsRow,
  analyticsTitle,
  nativeCode,
  productChange
} from '../model/products'

export function AnalyticsDetails({
  row,
  comparison,
  onClose
}: {
  row: AnalyticsRow
  comparison: boolean
  onClose: () => void
}) {
  const fields = [
    ['orders', 'Заказано'],
    ['buyouts', 'Выкуплено'],
    ['cancellations', 'Отмены и возвраты']
  ] as const
  return (
    <Dialog
      open
      onOpenChange={open => {
        if (!open) onClose()
      }}
    >
      <DialogContent className='product-dialog analytics-details-dialog'>
        <DialogHeader>
          <DialogTitle>{analyticsTitle(row)}</DialogTitle>
          <DialogDescription>
            {row.storeName} · {platformName(row.marketplace)}
          </DialogDescription>
        </DialogHeader>
        <div className='product-dialog-scroll'>
          <div className='analytics-details-grid'>
            <ProductGallery
              photos={row.current.photos ?? []}
              title={analyticsTitle(row)}
            />
            <div className='analytics-detail-content'>
              <div className='product-identifiers'>
                <div>
                  <span>Артикул продавца</span>
                  <CopyValue
                    value={row.current.vendor_code || '—'}
                    label='артикул продавца'
                  />
                </div>
                <div>
                  <span>{platformName(row.marketplace)}</span>
                  <CopyValue
                    value={nativeCode(row.current) || '—'}
                    label='артикул площадки'
                  />
                </div>
                {row.current.barcodes?.map(code => (
                  <div key={code}>
                    <span>Штрихкод</span>
                    <CopyValue
                      value={code}
                      label={`штрихкод ${code}`}
                    />
                  </div>
                ))}
              </div>
              <div className='analytics-detail-table'>
                <table>
                  <thead>
                    <tr>
                      <th>Показатель</th>
                      <th>Период</th>
                      {comparison && (
                        <>
                          <th>Прошлый</th>
                          <th>Изменение</th>
                        </>
                      )}
                    </tr>
                  </thead>
                  <tbody>
                    {fields.map(([field, label]) => (
                      <tr key={field}>
                        <td>{label}</td>
                        <td>
                          <strong>
                            {formatNumber(row.current[field])} шт.
                          </strong>
                          <small>
                            {row.currency
                              ? financeMoney(
                                  row.current[`${field}_amount`],
                                  row.currency
                                )
                              : '—'}
                          </small>
                        </td>
                        {comparison && (
                          <>
                            <td>
                              <strong>
                                {formatNumber(row.previous?.[field])}
                                {row.previous?.[field] != null ? ' шт.' : ''}
                              </strong>
                              <small>
                                {row.previousCurrency
                                  ? financeMoney(
                                      row.previous?.[`${field}_amount`],
                                      row.previousCurrency
                                    )
                                  : '—'}
                              </small>
                            </td>
                            <td>
                              {formatPercent(
                                productChange(row, field, 'units'),
                                { signed: true }
                              )}
                            </td>
                          </>
                        )}
                      </tr>
                    ))}
                    {[
                      ['Просмотры', row.current.opens, row.previous?.opens],
                      ['В корзину', row.current.carts, row.previous?.carts]
                    ].map(([label, current, previous]) => (
                      <tr key={String(label)}>
                        <td>{label}</td>
                        <td>{formatNumber(current)}</td>
                        {comparison && (
                          <>
                            <td>{formatNumber(previous)}</td>
                            <td>—</td>
                          </>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
