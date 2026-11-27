import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)

export default {
  trailingComma: 'none',
  tabWidth: 2,
  useTabs: false,
  semi: false,
  singleQuote: true,
  jsxSingleQuote: true,
  arrowParens: 'avoid',
  singleAttributePerLine: true,
  printWidth: 80,
  bracketSpacing: true,
  importOrder: [
    '<THIRD_PARTY_MODULES>',
    '^@app/types$',
    '^@app/constants$',
    '^@app/tokens$',
    '^@app/schemas$',
    '^@app/utils$',
    '^@app/api$',
    '^@app/hooks$',
    '^@app/ui$',
    '^@/components/(.*)$',
    '^@/features/(.*)$',
    '^@/hooks/(.*)$',
    '^@/lib/(.*)$',
    '^@/assets/(.*)$',
    '^(../.*)$',
    '^(./.*)$'
  ],
  importOrderSeparation: true,
  importOrderSortSpecifiers: true,
  plugins: [require.resolve('@trivago/prettier-plugin-sort-imports')]
}
