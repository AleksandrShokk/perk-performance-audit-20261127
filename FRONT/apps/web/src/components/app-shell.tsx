'use client'

import { useMutation } from '@tanstack/react-query'
import {
  ChartNoAxesCombined,
  Layers,
  LayoutDashboard,
  LogOut,
  Monitor,
  Moon,
  Package,
  Settings,
  Sun,
  Truck,
  UserRound,
  UsersRound,
  Wallet,
  Warehouse
} from 'lucide-react'
import { useTheme } from 'next-themes'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import type { ReactNode } from 'react'

import { useAuth } from '@/features/auth/auth-provider'
import { ConnectStore } from '@/features/workspace/connect-store'
import { ImportNotice } from '@/features/workspace/import-notice'
import { useWorkspace } from '@/features/workspace/workspace-provider'

import { usePrefetchSections } from '@/hooks/use-prefetch-sections'

import { ErrorNotice } from './feedback'
import { Logo } from './logo'
import { Button } from './ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from './ui/dropdown-menu'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from './ui/select'

const navigation = [
  { href: '/', label: 'Главная', icon: LayoutDashboard },
  {
    href: '/analytics',
    label: 'Аналитика',
    icon: ChartNoAxesCombined,
    permission: 'analytics.read' as const
  },
  {
    href: '/products',
    label: 'Товары',
    icon: Package,
    permission: 'inventory.read' as const
  },
  {
    href: '/finance',
    label: 'Финансы',
    icon: Wallet,
    permission: 'finance.read' as const
  },
  {
    href: '/inventory',
    label: 'Остатки',
    icon: Warehouse,
    permission: 'inventory.read' as const
  },
  {
    href: '/supplies',
    label: 'Поставки',
    icon: Truck,
    permission: 'inventory.read' as const
  }
]
export function AppShell({ children }: { children: ReactNode }) {
  const { user, signOut } = useAuth()
  const scope = useWorkspace()
  const { theme, setTheme } = useTheme()
  const pathname = usePathname()
  const prefetch = usePrefetchSections(pathname)
  const exit = useMutation({ mutationFn: signOut })
  const platform =
    scope.store?.marketplace === 'ozon'
      ? 'Ozon'
      : scope.store
        ? 'Wildberries'
        : 'Wildberries · Ozon'
  return (
    <div className='app-shell'>
      <a
        className='skip-link'
        href='#content'
      >
        Перейти к содержимому
      </a>
      <div className='workspace-area'>
        <div className='site-header'>
          <header className='topbar'>
            <Link
              href='/'
              className='header-logo'
              aria-label='PERK — главная'
            >
              <Logo />
            </Link>
            <div className='store-switcher'>
              {scope.stores.length > 0 && (
                <Select
                  value={scope.store?.id ?? 'all'}
                  onValueChange={scope.selectStore}
                >
                  <SelectTrigger
                    aria-label='Выбрать кабинет'
                    className='store-trigger'
                  >
                    <div className='store-mark'>
                      {scope.store ? (
                        scope.store.name.charAt(0).toUpperCase()
                      ) : (
                        <Layers size={18} />
                      )}
                    </div>
                    <span className='store-name'>
                      <strong>
                        <SelectValue placeholder='Выберите кабинет'>
                          {scope.store?.name ?? 'Все кабинеты'}
                        </SelectValue>
                      </strong>
                      <span>{platform}</span>
                    </span>
                  </SelectTrigger>
                  <SelectContent align='center'>
                    {scope.stores.length > 1 && (
                      <SelectItem value='all'>Все кабинеты</SelectItem>
                    )}
                    {scope.stores.map(store => (
                      <SelectItem
                        key={store.id}
                        value={store.id}
                      >
                        {store.name} ·{' '}
                        {store.marketplace === 'ozon' ? 'Ozon' : 'WB'}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </div>
            <div className='header-actions'>
              <ConnectStore compact />
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant='ghost'
                    size='icon'
                    className='avatar'
                    aria-label='Профиль и настройки'
                  >
                    <UserRound size={21} />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent
                  align='end'
                  className='min-w-64'
                >
                  <DropdownMenuLabel>{user?.email}</DropdownMenuLabel>
                  <DropdownMenuSeparator />
                  <DropdownMenuLabel>Оформление</DropdownMenuLabel>
                  <DropdownMenuRadioGroup
                    value={theme ?? 'system'}
                    onValueChange={setTheme}
                  >
                    <DropdownMenuRadioItem value='light'>
                      <Sun size={15} />
                      Светлая
                    </DropdownMenuRadioItem>
                    <DropdownMenuRadioItem value='dark'>
                      <Moon size={15} />
                      Тёмная
                    </DropdownMenuRadioItem>
                    <DropdownMenuRadioItem value='system'>
                      <Monitor size={15} />
                      Как в системе
                    </DropdownMenuRadioItem>
                  </DropdownMenuRadioGroup>
                  {scope.workspaces.length > 1 && (
                    <>
                      <DropdownMenuSeparator />
                      <DropdownMenuLabel>Компания</DropdownMenuLabel>
                      <DropdownMenuRadioGroup
                        value={scope.workspace?.id}
                        onValueChange={scope.selectWorkspace}
                      >
                        {scope.workspaces.map(workspace => (
                          <DropdownMenuRadioItem
                            key={workspace.id}
                            value={workspace.id}
                          >
                            {workspace.name}
                          </DropdownMenuRadioItem>
                        ))}
                      </DropdownMenuRadioGroup>
                    </>
                  )}
                  <DropdownMenuSeparator />
                  <DropdownMenuItem asChild>
                    <Link href='/settings/profile'>
                      <UserRound size={15} />
                      Профиль
                    </Link>
                  </DropdownMenuItem>
                  {scope.admin && (
                    <>
                      <DropdownMenuItem asChild>
                        <Link href='/settings'>
                          <Settings size={15} />
                          Кабинеты
                        </Link>
                      </DropdownMenuItem>
                      <DropdownMenuItem asChild>
                        <Link href='/settings/team'>
                          <UsersRound size={15} />
                          Команда
                        </Link>
                      </DropdownMenuItem>
                    </>
                  )}
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    onSelect={() => exit.mutate()}
                    disabled={exit.isPending}
                  >
                    <LogOut size={15} />
                    {exit.isPending ? 'Выходим…' : 'Выйти из аккаунта'}
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </header>
          <nav
            className='main-nav'
            aria-label='Разделы'
          >
            {navigation
              .filter(item =>
                item.href === '/products'
                  ? scope.can('inventory.read') || scope.can('profit.read')
                  : !item.permission || scope.can(item.permission)
              )
              .map(item => (
                <Link
                  key={item.href}
                  href={item.href}
                  prefetch={true}
                  onPointerEnter={() => void prefetch(item.href)}
                  onFocus={() => void prefetch(item.href)}
                  className={
                    pathname === item.href ? 'nav-item active' : 'nav-item'
                  }
                  aria-current={pathname === item.href ? 'page' : undefined}
                >
                  <item.icon size={17} />
                  <span>{item.label}</span>
                </Link>
              ))}
          </nav>
        </div>
        <main
          id='content'
          className='main-content'
        >
          <ErrorNotice error={exit.error} />
          <ImportNotice />
          {children}
        </main>
      </div>
    </div>
  )
}
