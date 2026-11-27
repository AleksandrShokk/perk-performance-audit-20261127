import * as SecureStore from 'expo-secure-store'

import type { SessionTokens } from './types'

export type { SessionTokens } from './types'

const KEY = 'perk.session'

export async function readTokens(): Promise<SessionTokens | null> {
  const saved = await SecureStore.getItemAsync(KEY)
  if (!saved) return null
  try {
    const tokens = JSON.parse(saved) as Partial<SessionTokens>
    if (
      typeof tokens.accessToken === 'string' &&
      typeof tokens.refreshToken === 'string'
    )
      return {
        accessToken: tokens.accessToken,
        refreshToken: tokens.refreshToken
      }
  } catch {
    // Повреждённая запись — просто войти заново.
  }
  await deleteTokens()
  return null
}

export function writeTokens(tokens: SessionTokens) {
  return SecureStore.setItemAsync(KEY, JSON.stringify(tokens))
}

export function deleteTokens() {
  return SecureStore.deleteItemAsync(KEY)
}
