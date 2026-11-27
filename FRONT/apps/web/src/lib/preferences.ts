'use client'

import { useSyncExternalStore } from 'react'

const event = 'perk:preference'
function subscribe(listener: () => void) {
  window.addEventListener('storage', listener)
  window.addEventListener(event, listener)
  return () => {
    window.removeEventListener('storage', listener)
    window.removeEventListener(event, listener)
  }
}
function read(key: string) {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

/** Only interface preferences. Reports, credentials and session tokens are never persisted. */
export function usePreference(key: string) {
  const value = useSyncExternalStore(
    subscribe,
    () => read(key),
    () => null
  )
  function setValue(next: string) {
    try {
      localStorage.setItem(key, next)
    } catch {
      /* Storage may be blocked by browser policy. */
    }
    window.dispatchEvent(new Event(event))
  }
  return [value, setValue] as const
}
