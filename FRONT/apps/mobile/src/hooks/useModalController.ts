import { useCallback, useEffect, useRef, useState } from 'react'
import { Platform } from 'react-native'

import { createModalLifecycle } from '@/lib/modalLifecycle'

/** iOS подтверждает закрытие через onDismiss; Android и web — после удаления окна из дерева. */
export function useModalController() {
  const [visible, setVisible] = useState(false)
  const [lifecycle] = useState(createModalLifecycle)
  const mounted = useRef(true)
  const open = useCallback(async () => {
    await lifecycle.open()
    if (mounted.current) setVisible(true)
  }, [lifecycle])
  const dismiss = useCallback(() => {
    const closed = lifecycle.dismiss()
    setVisible(false)
    return closed
  }, [lifecycle])
  const onDismiss = useCallback(() => lifecycle.didDismiss(), [lifecycle])
  useEffect(() => {
    if (!visible && Platform.OS !== 'ios') onDismiss()
  }, [visible, onDismiss])
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      void lifecycle.dismiss()
      lifecycle.didDismiss()
    }
  }, [lifecycle])
  return { visible, open, dismiss, onDismiss }
}
