# Sales and returns history

The operational `/api/v1/supplier/sales` method retains 90 days. Historical sales use
`POST /api/finance/v1/sales-reports/detailed`, with report history available from
2024-01-29. The existing finance import, cursor, rate limits, encrypted storage and
tenant authorization are reused. Importing a long sales period automatically includes
finance; a wholly historical period requests finance only. A sales schedule with
history enabled also schedules finance. Stored history is never trimmed to 90 days.

`GET .../analytics?date_from=...&date_to=...&sales_basis=auto|operational|reports`
has no 31-day, 90-day, or one-year limit. Auto uses one source for the entire selected
period: reports when the start predates operational retention, otherwise operational
events. The two sources are never added together. Explicit basis permits consistent
comparisons across short and long periods.

Report sales count `quantity` only for matching `operation` and `document_type`
equal to `Продажа` or `Возврат`, with positive quantity. Logistics, compensation,
storage, services and financial adjustments are not new customer purchases/returns.
Known correction rows and malformed sales rows are reported separately in
`sales_quality`; corrections do not inflate customer counts. This is a customer unit
view, not a corrected accounting turnover or profit calculation. ABC uses net units.

`sales_date_basis=report_date` groups history by `rrDate`, the date the operation
appears in the report. It must not be presented as the original purchase date.
The original limited records do not retain `saleDt`; extended finance records now do.
The historical chart still uses report_date rather than the original sale date.
Completeness proves the requested
report window was fetched, not that WB has finalized or published every future
correction. A report may lag operational data.

Report money is returned in `sales_money` by currency. Scalar monetary fields in
`sales`/`daily` are null for the report basis, so clients cannot add unlike currencies.
Finance payouts retain their previous meaning and are not profit.

Migration 0005 marks existing aggregate format as 1. Under the store lock,
`rebuild_store` atomically rebuilds finance aggregates from retained encrypted rows,
restores active previews, changes the revision and marks format 2. Until upgraded,
report sales expose `sales_metrics_ready=false` and cannot claim completeness.
Rollback preserves prior metrics. Subsequent imports update counts incrementally.
The dashboard cache is encrypted, tenant-scoped, includes basis, and uses version 3;
authorization and RLS precede every cache read. Worker warming upgrades old stores
and prepares common periods, without new WB requests.

The local console includes 1-year/2-year presets and explicit source selection. Its
sales table lists daily quantities for the same period and basis as the chart. Raw
operational events remain available at `/data/sales` for API consumers.

Official references:
- https://dev.wildberries.ru/docs/openapi/financial-reports-and-accounting
- https://dev.wildberries.ru/docs/openapi/reports
