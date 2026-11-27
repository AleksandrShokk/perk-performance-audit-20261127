import type { Metadata } from 'next'
import { headers } from 'next/headers'
import type { ReactNode } from 'react'

import { Providers } from '@/components/providers'
import { ThemeTokens } from '@/components/theme-tokens'

import './globals.css'

export const metadata: Metadata = {
  title: { default: 'PERK — аналитика магазинов', template: '%s · PERK' },
  description: 'Финансы, продажи и остатки Wildberries и Ozon.',
  robots: { index: false, follow: false }
}

export default async function RootLayout({
  children
}: {
  children: ReactNode
}) {
  const nonce = (await headers()).get('x-nonce') ?? undefined
  return (
    <html
      data-scroll-behavior='smooth'
      lang='ru'
      suppressHydrationWarning
    >
      <head>
        <ThemeTokens />
      </head>
      <body>
        <Providers nonce={nonce}>{children}</Providers>
      </body>
    </html>
  )
}

// Each HTML response receives its own CSP nonce.
export const dynamic = 'force-dynamic'
