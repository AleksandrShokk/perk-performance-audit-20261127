import type * as React from 'react'
import { beforeEach, expect, it, vi } from 'vitest'

import { ProductDisplayProvider } from '@/features/products/providers/ProductDisplayProvider'

const harness = vi.hoisted(() => ({
  userId: 'first' as string | undefined,
  state: undefined as unknown,
  effect: undefined as (() => void | (() => void)) | undefined,
  storage: new Map<string, string>(),
  getItem: vi.fn(),
  setItem: vi.fn()
}))
vi.mock('react', async original => ({
  ...(await original<typeof React>()),
  useState: (initial: unknown) => {
    harness.state ??= initial
    return [
      harness.state,
      (next: unknown) => {
        harness.state = typeof next === 'function' ? next(harness.state) : next
      }
    ]
  },
  useEffect: (effect: () => void | (() => void)) => {
    harness.effect = effect
  }
}))
vi.mock('@react-native-async-storage/async-storage', () => ({
  default: { getItem: harness.getItem, setItem: harness.setItem }
}))
vi.mock('@/features/auth/providers/AuthProvider', () => ({
  useAuth: () => ({ user: harness.userId ? { id: harness.userId } : undefined })
}))
const current = () => ProductDisplayProvider({ children: null }).props.value

beforeEach(() => {
  harness.userId = 'first'
  harness.state = undefined
  harness.storage.clear()
  harness.getItem
    .mockReset()
    .mockImplementation(async (key: string) => harness.storage.get(key) ?? null)
  harness.setItem
    .mockReset()
    .mockImplementation(async (key: string, value: string) => {
      harness.storage.set(key, value)
    })
})

it('восстанавливает сохранённый выбор после повторного открытия', async () => {
  current().setMode('vendor')
  await vi.waitFor(() =>
    expect(harness.storage.get('perk.product-label.first')).toBe('vendor')
  )
  harness.state = undefined
  current()
  harness.effect?.()
  await vi.waitFor(() => expect(current().mode).toBe('vendor'))
})

it('позднее чтение настроек не отменяет новый выбор', async () => {
  let resolve!: (value: string | null) => void
  harness.getItem.mockReturnValue(
    new Promise<string | null>(done => {
      resolve = done
    })
  )
  current()
  harness.effect?.()
  current().setMode('barcode')
  resolve('vendor')
  await vi.waitFor(() =>
    expect(harness.storage.get('perk.product-label.first')).toBe('barcode')
  )
  expect(current().mode).toBe('barcode')
})

it('не переносит выбор между аккаунтами', async () => {
  current().setMode('barcode')
  harness.userId = 'second'
  expect(current().mode).toBe('wb')
  current().setMode('vendor')
  await vi.waitFor(() =>
    expect(harness.storage.get('perk.product-label.second')).toBe('vendor')
  )
  expect(harness.storage.get('perk.product-label.first')).toBe('barcode')
  harness.userId = undefined
  expect(current().mode).toBe('wb')
})

it('по умолчанию показывает группы и восстанавливает флажок после перезапуска', async () => {
  expect(current().showAllVariants).toBe(false)
  current().setShowAllVariants(true)
  await vi.waitFor(() =>
    expect(harness.storage.get('perk.product-variants.first')).toBe('true')
  )
  harness.state = undefined
  current()
  harness.effect?.()
  await vi.waitFor(() => expect(current().showAllVariants).toBe(true))
})

it('позднее чтение флажка не отменяет нажатие и сохраняет отдельно настройку артикула', async () => {
  let resolve!: (value: string | null) => void
  harness.getItem.mockImplementation((key: string) =>
    key.startsWith('perk.product-variants.')
      ? new Promise<string | null>(done => {
          resolve = done
        })
      : Promise.resolve('vendor')
  )
  current()
  harness.effect?.()
  current().setShowAllVariants(false)
  resolve('true')
  await vi.waitFor(() => expect(current().mode).toBe('vendor'))
  expect(current().showAllVariants).toBe(false)
  await vi.waitFor(() =>
    expect(harness.storage.get('perk.product-variants.first')).toBe('false')
  )
})

it('флажок хранится отдельно для каждого аккаунта и сбрасывается при выходе', async () => {
  current().setShowAllVariants(true)
  await vi.waitFor(() =>
    expect(harness.storage.get('perk.product-variants.first')).toBe('true')
  )
  harness.userId = 'second'
  expect(current().showAllVariants).toBe(false)
  current().setShowAllVariants(false)
  await vi.waitFor(() =>
    expect(harness.storage.get('perk.product-variants.second')).toBe('false')
  )
  harness.userId = 'first'
  current()
  harness.effect?.()
  await vi.waitFor(() => expect(current().showAllVariants).toBe(true))
  harness.userId = undefined
  expect(current().showAllVariants).toBe(false)
})
