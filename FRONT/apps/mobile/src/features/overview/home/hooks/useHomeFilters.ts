import AsyncStorage from '@react-native-async-storage/async-storage'
import { useEffect, useState } from 'react'
import { z } from 'zod'

import { useAuth } from '@/features/auth/providers/AuthProvider'
import { rangeError } from '@/features/periods/model/periodRange'

import { DEFAULT_HOME_FILTERS, type HomeFilters } from '../model/overviewTypes'

const schema = z.object({
  period: z.union([
    z.literal('week'),
    z.literal(7),
    z.literal(14),
    z.literal(28),
    z
      .object({ date_from: z.string(), date_to: z.string() })
      .refine(range => !rangeError(range, 28))
  ]),
  unit: z.enum(['amount', 'units']),
  comparison: z.enum(['buyouts', 'previous'])
})

const storageKey = (userId: string) => `perk.home-filters.${userId}`
let writes = Promise.resolve()

/** Первый запуск — 7 дней. Фильтры сохраняются на устройстве отдельно для аккаунта. */
export function useHomeFilters() {
  const { user } = useAuth()
  const userId = user?.id
  const [saved, setSaved] = useState<{
    userId?: string
    filters: HomeFilters
    ready: boolean
  }>({ filters: DEFAULT_HOME_FILTERS, ready: false })

  useEffect(() => {
    if (!userId) return
    let active = true
    void AsyncStorage.getItem(storageKey(userId))
      .then(value => {
        if (!active) return
        let filters = DEFAULT_HOME_FILTERS
        try {
          const parsed = schema.safeParse(value ? JSON.parse(value) : null)
          if (parsed.success) filters = parsed.data
        } catch {
          // Старые или повреждённые настройки заменяются значениями по умолчанию.
        }
        setSaved(current =>
          current.userId === userId && current.ready
            ? current
            : { userId, filters, ready: true }
        )
      })
      .catch(() => {
        if (active)
          setSaved(current =>
            current.userId === userId && current.ready
              ? current
              : { userId, filters: DEFAULT_HOME_FILTERS, ready: true }
          )
      })
    return () => {
      active = false
    }
  }, [userId])

  const setFilters = (filters: HomeFilters) => {
    setSaved({ userId, filters, ready: true })
    if (userId)
      writes = writes
        .then(() =>
          AsyncStorage.setItem(storageKey(userId), JSON.stringify(filters))
        )
        .catch(() => {})
  }

  return {
    filters: saved.userId === userId ? saved.filters : DEFAULT_HOME_FILTERS,
    ready: !!userId && saved.userId === userId && saved.ready,
    setFilters
  }
}
