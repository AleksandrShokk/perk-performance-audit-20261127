// Копирует OpenAPI-схему бэкенда в пакет, чтобы генерация не зависела от запущенного API.
// Источник можно переопределить: PERK_OPENAPI=/path/to/openapi.json pnpm --filter @app/api schema
import { copyFileSync, existsSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const source = resolve(
  process.env.PERK_OPENAPI ?? resolve(root, '../../../BACK/docs/openapi.json')
)
const target = resolve(root, 'openapi.json')

if (!existsSync(source)) {
  console.error(`OpenAPI-схема не найдена: ${source}`)
  process.exit(1)
}

copyFileSync(source, target)
console.warn(`Схема обновлена: ${source} → ${target}`)

// Defaults and labels are generated from the authoritative backend/OpenAPI catalogue.
const catalogue = JSON.parse(readFileSync(target, 'utf8')).components.schemas
  .PermissionCatalogue.properties
const options = JSON.stringify(
  Object.entries(catalogue.permissions.default),
  null,
  2
)
const roles = JSON.stringify(catalogue.role_defaults.default, null, 2)
writeFileSync(
  resolve(root, '../analytics/src/permissions.generated.ts'),
  `// Generated from OpenAPI. Do not edit.\nexport const PERMISSION_OPTIONS = ${options} as const\nexport const ROLE_DEFAULTS: Record<string, string[]> = ${roles}\n`
)
