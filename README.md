# PERK — production performance audit snapshot

Captured on 27 November 2026 from the Moscow PERK production server.
Private source and metadata snapshot for performance review. This repository is not a deployment.

## Contents

- `BACK/` — backend source, tests and migrations from `/opt/perk/BACK`.
- `FRONT/` — Next.js web, Expo mobile and shared package source from `/opt/perk/FRONT`.
- `deploy/` — current Caddy, Docker Compose and backup service definitions, without environment values or secrets.
- `runtime/backend-images/` — actual Python application code from each distinct running backend image. Some background workers run an older image than the API.
- `audit/perk_schema.sql` — PostgreSQL schema only (`pg_dump --schema-only --no-owner --no-privileges --no-subscriptions`). No table rows or sequence values.
- `audit/perk_diag.txt` — aggregate database statistics, indexes and settings.
- `audit/environment.json` — selected runtime parameters, actual container image IDs, resource limits, Caddy configuration and scheduler intervals.
- `audit/source_manifest.json` — per-file hashes, origins, exclusions and redactions.
- `audit/secret-scan.json` — secret scanning summary.

## Database safety

All database connections enforced `default_transaction_read_only=on`. Diagnostic statements used `BEGIN TRANSACTION READ ONLY`, short statement timeouts and lock timeouts. No migrations, writes, vacuum, table data exports, configuration changes or service restarts were performed.

`pg_stat_statements` is not installed or preloaded in this instance. It was not installed for this collection, so historical expensive-query timings are unavailable. Table row counts in the diagnostics are PostgreSQL estimates, not exported records. Query text, if available, is restricted to redacted shapes.

## Running code versions

- `perk-production-api-1` → `sha256:139d35077fcd4ebfdffe` → `runtime/backend-images/139d35077fcd/app`
- `perk-production-worker-heavy-1` → `sha256:139d35077fcd4ebfdffe` → `runtime/backend-images/139d35077fcd/app`
- `perk-production-worker-ozon-1` → `sha256:c654e393be3c6da925df` → `runtime/backend-images/c654e393be3c/app`
- `perk-production-worker-1` → `sha256:c654e393be3c6da925df` → `runtime/backend-images/c654e393be3c/app`
- `perk-production-beat-1` → `sha256:c654e393be3c6da925df` → `runtime/backend-images/c654e393be3c/app`

Use the runtime image snapshots to review the code actually executing ingestion jobs; use `BACK/` for the current on-server source. Image tags alone are not reliable version identifiers because some running containers reference an older image under the same tag.

## Secrets and exclusions

No `.env` files, secret directories, credentials, dependency installations, compiled Next.js output, database dumps, uploaded reports or server backup contents are included. Environment example files were also omitted conservatively. Firebase client configuration was omitted. No marketplace token rows were read from the database.

Credential-like literals were conservatively masked in these audit-copy files (the production originals were not changed):

- `BACK/tests/test_ozon_order_prices.py`
- `BACK/tests/test_team_links.py`
- `BACK/deploy/README.md`

Those copies may require synthetic test values to run the affected tests. All other exported files retain their server content hashes, recorded in the manifest. There is no inherited Git history in this repository. Both existing private PERK repositories were separately scanned across all their commits.

## Review scope

Focus on ingestion pagination, rate limiting/retries, transaction boundaries, bulk persistence, encrypted metric aggregation, report snapshot invalidation, scheduler frequency, query/index use and frontend request waterfalls. No performance changes are applied by this snapshot.
