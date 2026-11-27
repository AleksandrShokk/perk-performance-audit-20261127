import next from 'eslint-config-next/core-web-vitals'
import ts from 'eslint-config-next/typescript'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  ...next,
  ...ts,
  globalIgnores([
    '.next/**',
    'next-env.d.ts',
    'playwright-report/**',
    'test-results/**'
  ]),
  {
    rules: {
      '@typescript-eslint/consistent-type-imports': [
        'error',
        { prefer: 'type-imports', fixStyle: 'inline-type-imports' }
      ],
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }
      ]
    }
  }
])
