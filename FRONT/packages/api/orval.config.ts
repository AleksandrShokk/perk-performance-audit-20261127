import { defineConfig } from 'orval'

const input = { target: './openapi.json' }

export default defineConfig({
  /** Типы, функции запросов и хуки React Query. */
  perk: {
    input,
    output: {
      mode: 'tags-split',
      target: './src/generated/endpoints',
      schemas: './src/generated/models',
      client: 'react-query',
      httpClient: 'axios',
      clean: true,
      override: {
        mutator: { path: './src/client.ts', name: 'apiClient' },
        query: { signal: true }
      }
    }
  },
  /** Zod-схемы тел запросов и ответов: основа для проверки форм. */
  perkZod: {
    input,
    output: {
      mode: 'tags-split',
      target: './src/generated/zod',
      client: 'zod',
      fileExtension: '.zod.ts',
      clean: true
    }
  }
})
