import type { Page } from '@playwright/test'

import type { ProductItem, ProductModel, ProductVariant } from '@app/api'

import { mockApi, ozon, wb, wid } from './fixtures'

export const ozonVariantId = '80000000-0000-4000-8000-000000000001'
function size(
  id: string,
  label: string,
  stock: number | null,
  price: string | null,
  barcode: string
): ProductVariant {
  return {
    id,
    chrt_id: id,
    size: label,
    stock,
    unit_cost: price,
    barcodes: [barcode],
    to_client: 1,
    from_client: 0,
    warehouses: stock == null ? [] : [{ name: 'Коледино', quantity: stock }]
  }
}
function product(
  code: string,
  title: string,
  color: string,
  variants: ProductVariant[],
  photos: string[] = []
): ProductItem {
  return {
    id: `product-${code}`,
    nm_id: code,
    external_id: code,
    marketplace_code: code,
    marketplace: 'wildberries',
    vendor_code: `ART-${code}`,
    store_id: wb,
    store_name: 'PERK Test WB',
    title,
    brand: 'TWL',
    subject: 'Мотоэкипировка',
    colors: color ? [color] : [],
    photos,
    variants,
    stock: variants.some(row => row.stock == null)
      ? null
      : variants.reduce((sum, row) => sum + row.stock!, 0),
    stock_updated_at: '2026-11-06T00:00:00Z',
    stock_stale: false,
    missing_cost_variants: variants.filter(row => row.unit_cost == null).length
  }
}
function card(
  id: string,
  title: string,
  products: ProductItem[]
): ProductModel {
  return {
    id,
    title,
    products,
    brand: 'TWL',
    store_id: products[0]!.store_id,
    store_name: products[0]!.store_name,
    marketplace: products[0]!.marketplace!,
    grouping: 'marketplace',
    stock: products.some(product => product.stock == null)
      ? null
      : products.reduce((sum, product) => sum + product.stock!, 0),
    missing_cost_variants: products.reduce(
      (sum, product) => sum + (product.missing_cost_variants ?? 0),
      0
    )
  }
}
export async function mockProducts(
  page: Page,
  options: {
    permissions?: string[]
    holdWrite?: Promise<void>
    loading?: boolean
    empty?: boolean
  } = {}
) {
  await mockApi(page)
  const black = {
    ...product(
      '101',
      'Мотоперчатки Urban, чёрные',
      'чёрный',
      [
        size('10101', 'M', 8, '1250.1234', '00010101'),
        size('10102', 'L', 5, '1300', '00010102')
      ],
      [
        'https://images.perk.test/black-front.svg',
        'https://images.perk.test/black-back.svg'
      ]
    ),
    vendor_code: 'GLOVE-BLACK'
  }
  const blue = {
    ...product(
      '102',
      'Мотоперчатки Urban, синие',
      'синий',
      [
        size('10201', 'M', 4, '1400', '00010201'),
        size('10202', 'L', 2, '1450', '00010202')
      ],
      ['https://images.perk.test/blue-front.svg']
    ),
    vendor_code: 'GLOVE-BLUE'
  }
  const helmet = product('201', 'Мотошлем Trail', 'серый', [
    size('20101', 'L', 0, null, '00020101')
  ])
  const boot = {
    ...product(
      '301',
      'Мотоботы Track',
      'чёрный',
      [size(ozonVariantId, '42', 12, '3500', '00900101')],
      [
        'https://images.perk.test/ozon-front.svg',
        'https://images.perk.test/ozon-back.svg'
      ]
    ),
    id: '70000000-0000-4000-8000-000000000001',
    store_id: ozon,
    store_name: 'PERK Test Ozon',
    marketplace: 'ozon',
    nm_id: '',
    marketplace_code: '900101',
    external_id: '300101',
    vendor_code: 'BOOT-42'
  }
  const models = [
    card('wb-native-1', 'Мотоперчатки Urban', [black, blue]),
    card('wb-native-2', 'Мотошлем Trail', [helmet]),
    ...Array.from({ length: 25 }, (_, i) =>
      card(`wb-native-${i + 3}`, `Модель ${i + 1}`, [
        product(String(1000 + i), `Модель ${i + 1}`, 'чёрный', [
          size(
            String(100000 + i),
            '0',
            i === 0 ? null : i + 1,
            '500',
            `000${100000 + i}`
          )
        ])
      ])
    ),
    card('ozon-native-1', 'Мотоботы Track', [boot])
  ]
  const state = {
    models,
    catalogRequests: [] as string[],
    writes: [] as { path: string; body: Record<string, string> }[],
    costReads: [] as string[],
    csrf: true
  }
  const book: {
    nm_id?: string
    variant_id?: string
    barcode?: string
    amount: string
    currency: string
    effective_from: string
    created_at: string
  }[] = [
    {
      nm_id: '101',
      barcode: '',
      amount: '1100',
      currency: 'RUB',
      effective_from: '2025-01-01',
      created_at: '2025-01-01T00:00:00Z'
    },
    {
      nm_id: '101',
      barcode: '00010101',
      amount: '1250.1234',
      currency: 'RUB',
      effective_from: '2026-01-01',
      created_at: '2026-01-01T00:00:00Z'
    },
    {
      variant_id: ozonVariantId,
      amount: '3500',
      currency: 'RUB',
      effective_from: '2026-01-01',
      created_at: '2026-01-01T00:00:00Z'
    }
  ]
  await page.route('https://images.perk.test/**', route => {
    const color = route.request().url().includes('blue')
      ? '#6d83c5'
      : route.request().url().includes('ozon')
        ? '#3e435a'
        : '#45445e'
    return route.fulfill({
      contentType: 'image/svg+xml',
      body: `<svg xmlns="http://www.w3.org/2000/svg" width="520" height="620" viewBox="0 0 520 620"><rect width="520" height="620" fill="#f2f1f8"/><path d="M150 455V252q0-18 17-18h10V160q0-24 20-24t20 24v100h12V120q0-24 20-24t20 24v140h12V140q0-24 20-24t20 24v120h12v-75q0-24 20-24t20 24v175q0 35-20 65l-10 30z" fill="${color}"/><path d="M170 350h170M195 275h100" stroke="#aaa3ed" stroke-width="14" stroke-linecap="round"/><text x="260" y="548" font-family="Arial" font-size="22" text-anchor="middle" fill="#717185">TWL</text></svg>`
    })
  })
  await page.route('**/api/v1/**', async route => {
    const req = route.request(),
      url = new URL(req.url()),
      path = url.pathname
    const json = (data: unknown, status = 200) =>
      route.fulfill({
        status,
        contentType: 'application/json',
        body: JSON.stringify(data)
      })
    if (options.permissions && path.endsWith('/workspaces'))
      return json([
        {
          id: wid,
          name: 'PERK Test',
          role: 'manager',
          permissions: options.permissions,
          store_ids: null
        }
      ])
    if (path.endsWith('/product-models')) {
      state.catalogRequests.push(req.url())
      const store = url.searchParams.get('store_id'),
        q = (url.searchParams.get('q') ?? '').toLowerCase(),
        offset = Number(url.searchParams.get('offset') ?? 0),
        limit = Number(url.searchParams.get('limit') ?? 20)
      const filtered =
        options.empty || (options.loading && state.catalogRequests.length === 1)
          ? []
          : models.filter(
              model =>
                (!store || model.store_id === store) &&
                (!q ||
                  [
                    model.title,
                    ...model.products.flatMap(product => [
                      product.title,
                      product.vendor_code,
                      product.nm_id,
                      product.marketplace_code,
                      ...product.variants.flatMap(row => row.barcodes)
                    ])
                  ].some(value => value?.toLowerCase().includes(q))) &&
                (url.searchParams.get('in_stock') !== 'true' ||
                  model.products.some(product => (product.stock ?? 0) > 0)) &&
                (url.searchParams.get('missing_cost') !== 'true' ||
                  model.products.some(product =>
                    product.variants.some(row => row.unit_cost == null)
                  ))
            )
      return json({
        items: filtered.slice(offset, offset + limit),
        total: filtered.length,
        total_products: filtered.reduce(
          (sum, item) => sum + item.products.length,
          0
        ),
        total_variants: filtered.reduce(
          (sum, item) =>
            sum +
            item.products.reduce(
              (count, product) => count + product.variants.length,
              0
            ),
          0
        ),
        currency: 'RUB',
        limit,
        offset,
        is_loading: !!options.loading && state.catalogRequests.length === 1,
        is_partial: !!options.loading && state.catalogRequests.length === 1
      })
    }
    if (!path.endsWith('/costs') && !path.endsWith('/variant-costs'))
      return route.fallback()
    if (req.method() === 'GET') {
      state.costReads.push(req.url())
      const nm = url.searchParams.get('nm_id'),
        variant = url.searchParams.get('variant_id'),
        offset = Number(url.searchParams.get('offset') ?? 0)
      return json(
        book
          .filter(row =>
            variant ? row.variant_id === variant : row.nm_id === nm
          )
          .slice(offset, offset + 50)
      )
    }
    const body = req.postDataJSON() as Record<string, string>
    state.csrf &&= req.headers()['x-csrf-token'] === 'pc_test'
    if (options.holdWrite) await options.holdWrite
    state.writes.push({ path, body })
    book.push({
      ...body,
      amount: body.amount!,
      currency: body.currency!,
      effective_from: body.effective_from!,
      created_at: new Date().toISOString()
    })
    for (const model of models)
      for (const product of model.products)
        for (const variant of product.variants)
          if (
            body.variant_id
              ? variant.id === body.variant_id
              : product.nm_id === body.nm_id &&
                (!body.barcode || variant.barcodes.includes(body.barcode))
          )
            variant.unit_cost = body.amount!
    return json({ ...body, created_at: new Date().toISOString() })
  })
  return state
}
