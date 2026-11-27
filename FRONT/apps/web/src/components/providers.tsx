'use client'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ThemeProvider } from 'next-themes'
import { type ReactNode, useState } from 'react'

import { configureValidationMessages } from '@app/schemas'

import { TooltipProvider } from '@/components/ui/tooltip'

import { AuthProvider } from '@/features/auth/auth-provider'
import { StepUpProvider } from '@/features/auth/step-up-provider'
import { PendingInviteProvider } from '@/features/team/pending-invite'
import { WorkspaceProvider } from '@/features/workspace/workspace-provider'

import { statusOf } from '@/lib/errors'

configureValidationMessages()

export function Providers({
  children,
  nonce
}: {
  children: ReactNode
  nonce?: string
}) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 60000,
            gcTime: 15 * 60 * 1000,
            retry: (count, error) =>
              count < 1 &&
              ![400, 401, 403, 404, 409, 422, 429].includes(
                statusOf(error) ?? 0
              ),
            refetchOnWindowFocus: true
          },
          mutations: { retry: false }
        }
      })
  )
  return (
    <ThemeProvider
      nonce={nonce}
      attribute='class'
      defaultTheme='system'
      enableSystem
      disableTransitionOnChange
    >
      <QueryClientProvider client={client}>
        <AuthProvider>
          <WorkspaceProvider>
            <TooltipProvider delayDuration={200}>
              <PendingInviteProvider>
                <StepUpProvider>{children}</StepUpProvider>
              </PendingInviteProvider>
            </TooltipProvider>
          </WorkspaceProvider>
        </AuthProvider>
      </QueryClientProvider>
    </ThemeProvider>
  )
}
