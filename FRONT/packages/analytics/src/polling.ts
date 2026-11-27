/** Bound background traffic; slow unchanged/error states never poll aggressively. */
export type PollData = {
  is_loading?: boolean
  loading?: boolean
  status?: string
  is_partial?: boolean
  error_code?: string | null
  freshness?: { stale: boolean }
}
export function reportInterval(data?: PollData) {
  if (data?.error_code) return 60_000
  const active =
    data?.is_loading ||
    data?.loading ||
    data?.is_partial ||
    data?.status === 'preparing' ||
    data?.status === 'partial'
  return active ? 10_000 : 60_000
}
export function progressInterval(
  started: number,
  stores = 1,
  now = Date.now()
) {
  return Math.max(
    stores > 2 ? stores * 2500 : 5000,
    now - started > 60_000 ? 15_000 : 5000
  )
}
