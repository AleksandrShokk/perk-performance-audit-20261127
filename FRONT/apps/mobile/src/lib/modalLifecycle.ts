/** Ожидание фактического закрытия окна, прежде чем показать следующее. */
export function createModalLifecycle() {
  let visible = false
  let closing: Promise<void> | undefined
  let resolve: (() => void) | undefined
  return {
    async open() {
      await closing
      visible = true
    },
    dismiss() {
      if (!visible) return closing ?? Promise.resolve()
      visible = false
      closing = new Promise<void>(done => {
        resolve = done
      })
      return closing
    },
    didDismiss() {
      const done = resolve
      closing = undefined
      resolve = undefined
      done?.()
    }
  }
}
