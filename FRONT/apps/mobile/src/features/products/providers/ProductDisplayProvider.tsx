import AsyncStorage from '@react-native-async-storage/async-storage'
import { type ReactNode, createContext, use, useEffect, useState } from 'react'

import { useAuth } from '@/features/auth/providers/AuthProvider'

import {
  type ProductLabelMode,
  parseProductLabelMode
} from '../model/productLabel'

const ProductDisplayContext = createContext<{
  mode: ProductLabelMode
  setMode: (mode: ProductLabelMode) => void
  showAllVariants: boolean
  setShowAllVariants: (value: boolean) => void
} | null>(null)
const storageKey = (userId: string) => `perk.product-label.${userId}`
const variantsKey = (userId: string) => `perk.product-variants.${userId}`
const defaults = {
  mode: 'wb' as ProductLabelMode,
  showAllVariants: false,
  modeReady: false,
  variantsReady: false
}
let writes = Promise.resolve()

export function ProductDisplayProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  const userId = user?.id
  const [saved, setSaved] = useState<{ userId?: string } & typeof defaults>(
    defaults
  )
  useEffect(() => {
    if (!userId) return
    let active = true
    void Promise.allSettled([
      AsyncStorage.getItem(storageKey(userId)),
      AsyncStorage.getItem(variantsKey(userId))
    ]).then(([label, variants]) => {
      if (!active) return
      setSaved(previous => {
        const current = previous.userId === userId ? previous : defaults
        return {
          userId,
          mode: current.modeReady
            ? current.mode
            : parseProductLabelMode(
                label.status === 'fulfilled' ? label.value : null
              ),
          showAllVariants: current.variantsReady
            ? current.showAllVariants
            : variants.status === 'fulfilled' && variants.value === 'true',
          modeReady: true,
          variantsReady: true
        }
      })
    })
    return () => {
      active = false
    }
  }, [userId])

  const setMode = (mode: ProductLabelMode) => {
    setSaved(current => ({
      ...(current.userId === userId ? current : defaults),
      userId,
      mode,
      modeReady: true
    }))
    if (userId)
      writes = writes
        .then(() => AsyncStorage.setItem(storageKey(userId), mode))
        .catch(() => {})
  }
  const setShowAllVariants = (showAllVariants: boolean) => {
    setSaved(current => ({
      ...(current.userId === userId ? current : defaults),
      userId,
      showAllVariants,
      variantsReady: true
    }))
    if (userId)
      writes = writes
        .then(() =>
          AsyncStorage.setItem(variantsKey(userId), String(showAllVariants))
        )
        .catch(() => {})
  }
  const current = saved.userId === userId ? saved : defaults
  return (
    <ProductDisplayContext
      value={{
        mode: current.mode,
        setMode,
        showAllVariants: current.showAllVariants,
        setShowAllVariants
      }}
    >
      {children}
    </ProductDisplayContext>
  )
}

export function useProductDisplay() {
  const value = use(ProductDisplayContext)
  if (!value)
    throw new Error('useProductDisplay вызван вне ProductDisplayProvider')
  return value
}
