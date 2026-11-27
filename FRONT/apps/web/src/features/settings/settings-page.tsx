'use client'

import Link from 'next/link'

import { AppShell } from '@/components/app-shell'
import { Empty, ErrorNotice, Loading } from '@/components/feedback'

import { useAuth } from '@/features/auth/auth-provider'
import { RequireAuth } from '@/features/auth/require-auth'
import { useWorkspace } from '@/features/workspace/workspace-provider'

import { ProfileSettings } from './profile/profile-settings'
import { StoresSettings } from './stores/stores-settings'
import { TeamSettings } from './team/team-settings'

type Section = 'stores' | 'team' | 'profile'
const sections = [
  ['stores', 'Кабинеты', '/settings'],
  ['team', 'Команда', '/settings/team'],
  ['profile', 'Профиль', '/settings/profile']
] as const
export function SettingsPage({ section = 'stores' }: { section?: Section }) {
  const { user } = useAuth(),
    scope = useWorkspace()
  return (
    <RequireAuth>
      <SettingsContent
        key={`${user?.id}:${scope.accessKey}`}
        section={section}
      />
    </RequireAuth>
  )
}
function SettingsContent({ section }: { section: Section }) {
  const scope = useWorkspace()
  return (
    <AppShell>
      <div className='page-heading'>
        <h1>Настройки</h1>
      </div>
      <nav
        className='settings-nav'
        aria-label='Настройки'
      >
        {sections
          .filter(([key]) => key === 'profile' || scope.admin)
          .map(([key, label, href]) => (
            <Link
              href={href}
              aria-current={section === key ? 'page' : undefined}
              className={section === key ? 'active' : ''}
              key={key}
            >
              {label}
            </Link>
          ))}
      </nav>
      <ErrorNotice
        error={scope.error}
        onRetry={() => void scope.refresh()}
      />
      {scope.loading ? (
        <Loading />
      ) : section !== 'profile' && !scope.admin ? (
        <Empty title='Нет доступа к настройкам компании' />
      ) : section === 'stores' ? (
        <StoresSettings />
      ) : section === 'team' ? (
        <TeamSettings />
      ) : (
        <ProfileSettings />
      )}
    </AppShell>
  )
}
