import AsyncStorage from '@react-native-async-storage/async-storage'
import { createAsyncStoragePersister } from '@tanstack/query-async-storage-persister'
import { QueryClient } from '@tanstack/react-query'
import type { PersistQueryClientProviderProps } from '@tanstack/react-query-persist-client'

import { errorStatus } from './errors'

const DAY = 24 * 60 * 60 * 1000

declare module '@tanstack/react-query' {
  interface Register {
    /** Совместимость с метаданными запросов. Ответы хранятся только в памяти. */
    queryMeta: { persist?: boolean }
  }
}

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      // Должно быть не меньше maxAge сохранённого кэша, иначе он отбрасывается.
      gcTime: DAY,
      retry: (failures, error) => {
        const status = errorStatus(error)
        return failures < 2 && !(status && status < 500)
      }
    },
    mutations: { retry: false, gcTime: 0 }
  }
})

let cacheGeneration = 0
let storageQueue = Promise.resolve()

function updateStorage(action: () => Promise<void>) {
  const operation = storageQueue.then(action)
  storageQueue = operation.catch(() => {})
  return operation
}

function createPersister() {
  const generation = cacheGeneration
  return createAsyncStoragePersister({
    storage: {
      getItem: key => AsyncStorage.getItem(key),
      setItem: (key, value) =>
        updateStorage(async () => {
          // Отложенная запись старой сессии после выхода отбрасывается.
          if (generation === cacheGeneration)
            await AsyncStorage.setItem(key, value)
        }),
      removeItem: key => updateStorage(() => AsyncStorage.removeItem(key))
    },
    key: 'perk.query-cache',
    throttleTime: 1000
  })
}

let currentPersister = createPersister()
const persister: ReturnType<typeof createPersister> = {
  persistClient: client => currentPersister.persistClient(client),
  restoreClient: () => currentPersister.restoreClient(),
  removeClient: () => currentPersister.removeClient()
}

/** На диск не попадают ответы API. Новый buster удаляет прежний открытый кэш. */
export const persistOptions: PersistQueryClientProviderProps['persistOptions'] =
  {
    persister,
    maxAge: DAY,
    buster: 'v3-no-private-disk-cache',
    dehydrateOptions: {
      shouldDehydrateMutation: () => false,
      shouldDehydrateQuery: () => false
    }
  }

/** Выход или чужой аккаунт: кэш одного пользователя не должен достаться другому. */
export async function resetQueryCache() {
  cacheGeneration += 1
  currentPersister = createPersister()
  await queryClient.cancelQueries()
  queryClient.clear()
  await persister.removeClient()
}
