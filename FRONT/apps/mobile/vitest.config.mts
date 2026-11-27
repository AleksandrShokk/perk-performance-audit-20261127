import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
      '@app/api/zod': fileURLToPath(
        new URL('../../packages/api/src/zod.ts', import.meta.url)
      ),
      '@app/api': fileURLToPath(
        new URL('../../packages/api/src/index.ts', import.meta.url)
      ),
      '@app/schemas': fileURLToPath(
        new URL('../../packages/schemas/src/index.ts', import.meta.url)
      )
    }
  },
  test: {
    environment: 'node',
    setupFiles: ['./tests/setup.ts'],
    include: ['tests/**/*.test.ts'],
    env: { EXPO_PUBLIC_API_URL: 'http://api.test/api/v1' }
  }
})
