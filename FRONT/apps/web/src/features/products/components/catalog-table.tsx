import { formatNumber } from '@app/analytics/format'

import { ProductLabel } from '@/components/product-label'
import { TablePagination } from '@/components/table-pagination'

import { ReportHint } from '@/features/finance/components/report-hint'

import {
  type CatalogRow,
  type IdentifierMode,
  costRange,
  identifier,
  platformName
} from '../model/catalog'

export function CatalogTable({
  rows,
  page,
  total,
  currency,
  mode,
  canStock,
  canCost,
  busy,
  onOpen,
  onPage,
  pageSize,
  onPageSize
}: {
  rows: CatalogRow[]
  page: number
  total: number
  currency: string
  mode: IdentifierMode
  canStock: boolean
  canCost: boolean
  busy: boolean
  onOpen: (row: CatalogRow) => void
  onPage: (page: number) => void
  pageSize: number
  onPageSize: (size: number) => void
}) {
  return (
    <section
      className='surface catalog-table'
      aria-label='Каталог товаров'
    >
      <div className='catalog-table-scroll'>
        <table className='catalog-data'>
          <thead>
            <tr>
              <th>Товар</th>
              <th className='catalog-code'>Артикул</th>
              <th className='catalog-store'>Кабинет</th>
              <th className='catalog-variants'>Состав</th>
              {canStock && <th>FBO</th>}
              {canCost && (
                <th>
                  Себестоимость
                  <ReportHint label='О себестоимости в каталоге'>
                    Цены известных размеров. «—» — цена не указана.
                  </ReportHint>
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {rows.map(row => {
              const first = row.products[0]
              const code = first
                ? `${identifier(first, mode, first.marketplace)}${row.products.length > 1 ? ` · ещё ${row.products.length - 1}` : ''}`
                : '—'
              const cost = canCost
                ? costRange(row.products, currency)
                : { label: '—', partial: false }
              return (
                <tr key={row.key}>
                  <td>
                    <button
                      className='catalog-product-button'
                      aria-label={`Открыть ${row.title} · ${first?.vendor_code || row.model.store_name}`}
                      onClick={() => onOpen(row)}
                    >
                      <ProductLabel
                        title={row.title}
                        article={code}
                        photo={first?.photos?.[0]}
                      />
                      <span className='catalog-mobile-store'>
                        {row.model.store_name} ·{' '}
                        {platformName(row.model.marketplace)}
                      </span>
                    </button>
                  </td>
                  <td className='catalog-code'>{code}</td>
                  <td className='catalog-store'>
                    <span>{row.model.store_name}</span>
                    <small>{platformName(row.model.marketplace)}</small>
                  </td>
                  <td className='catalog-variants'>
                    <strong>
                      Артикулы: {formatNumber(row.products.length)}
                    </strong>
                    <small>
                      Варианты:{' '}
                      {formatNumber(
                        row.products.reduce(
                          (sum, product) => sum + product.variants.length,
                          0
                        )
                      )}
                    </small>
                  </td>
                  {canStock && (
                    <td className='catalog-stock'>
                      {formatNumber(row.stock)}
                      {row.stock != null && <small>шт.</small>}
                    </td>
                  )}
                  {canCost && (
                    <td className='catalog-cost'>
                      {cost.label}
                      {cost.partial && cost.label !== '—' && (
                        <ReportHint
                          label={`О заполнении себестоимости ${row.title}`}
                        >
                          Цена заполнена не для всех размеров.
                        </ReportHint>
                      )}
                    </td>
                  )}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <div className='table-footer'>
        <span>
          {total
            ? `${page * pageSize + 1}–${Math.min((page + 1) * pageSize, total)} карточек из ${formatNumber(total)}`
            : '0 карточек'}
        </span>
        <TablePagination
          label='каталога'
          page={page}
          pageSize={pageSize}
          total={total}
          busy={busy}
          onPage={onPage}
          onPageSize={onPageSize}
        />
      </div>
    </section>
  )
}
