import { fileURLToPath } from 'node:url'

import type { NextConfig } from 'next'

const apiOrigin = process.env.API_ORIGIN ?? 'http://127.0.0.1:8000'
const nextConfig: NextConfig = {
  output: 'standalone',
  outputFileTracingRoot: fileURLToPath(new URL('../../', import.meta.url)),
  poweredByHeader: false,
  transpilePackages: [
    '@app/api',
    '@app/schemas',
    '@app/tokens',
    '@app/analytics'
  ],
  async rewrites() {
    return [
      { source: '/api/v1/:path*', destination: `${apiOrigin}/api/v1/:path*` }
    ]
  },
  async headers() {
    return [
      {
        source: '/:path*',
        headers: [
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
          { key: 'X-Frame-Options', value: 'DENY' },
          { key: 'X-Robots-Tag', value: 'noindex, nofollow' }
        ]
      }
    ]
  }
}
export default nextConfig
