# WB import and dashboard latency

- Initial priority is the last 30 completed days. Longer history runs afterwards.
- Operational sales retention is 90 days; financial reports start on 2024-01-29.
- History uses wide date windows and up to 100,000 financial rows per request. A
  response is bounded at 64 MiB, and an import at 1,000,000 normalized records.
  Oversized responses reduce the page size; oversized history reduces the window.
- Quotas are shared by seller, method and token type, never by token string or store.
  Service tokens are conservatively grouped within that seller/type. Provider retry
  headers always override local minimum intervals. Unattributed old cooldowns are
  inherited; confirmed Basic-to-Personal transitions preserve the Basic cooldown
  separately. They do not reset another Personal token's quota.
- Dispatch checks due pages every two seconds, without sleeping inside import jobs.
  Request cooldowns elapse while downloading, normalizing and writing database rows.
  Provider waits count from receipt of response headers rather than the end of
  downloading a large body.
- Publication uses batches of 1,000 rows inside a single transaction, preserving
  atomic visibility without exceeding the normal five-second SQL statement limit.
- Dashboard caches remain encrypted and authorization precedes every cache read.
  Readers do not wait on the import's store lock. Revision checks prevent caching
  aggregates under an obsolete publication/preview revision.
- After a successful publication, a separate owner-scoped task warms common chart
  periods and the full financial history. A periodic task covers lost warm-up jobs.
- A partial period is explicitly marked incomplete. Financial chart values are
  report-date payouts per currency, not operational sale dates or profit.

Measure first import duration separately from cached dashboard latency. Wildberries
can impose waits or return errors; a universal 2–3 minute initial import SLA is not
possible for arbitrary seller volumes.
