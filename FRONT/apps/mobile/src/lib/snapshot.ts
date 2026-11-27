import type { QueryKey } from '@tanstack/react-query'

import { http } from '@app/api'

import { queryClient } from './queryClient'

/**
 * Снимок отчёта: данные и ETag. Сервер хранит готовые снимки; при повторном
 * запросе с If-None-Match отвечает пустым 304, и мы оставляем сохранённую копию.
 */
export type Snapshot<T> = { data: T; etag: string | null }

type Fresh = { freshness: { stale: boolean }; is_loading?: boolean }

export async function fetchSnapshot<T>(
  url: string,
  queryKey: QueryKey,
  signal: AbortSignal
): Promise<Snapshot<T>> {
  const cached = queryClient.getQueryData<Snapshot<T>>(queryKey)
  const response = await http.get<T>(url, {
    signal,
    headers: cached?.etag ? { 'If-None-Match': cached.etag } : undefined,
    validateStatus: status => status === 200 || status === 304
  })
  if (response.status === 304) {
    if (cached) return cached
    throw new Error('304 без сохранённого снимка')
  }
  const etag = response.headers.etag
  return { data: response.data, etag: typeof etag === 'string' ? etag : null }
}

/** Неизменившиеся снимки не запускают частый бесконечный опрос. */
export function refetchWhileStale<T extends Fresh>(snapshot?: Snapshot<T>) {
  return snapshot?.data.is_loading
    ? 10000
    : snapshot?.data.freshness.stale
      ? 60000
      : false
}
