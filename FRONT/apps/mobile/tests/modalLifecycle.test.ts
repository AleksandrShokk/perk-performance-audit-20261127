import { expect, it, vi } from 'vitest'

import { createModalLifecycle } from '@/lib/modalLifecycle'

it('закрытие ждёт подтверждения iOS, поэтому следующее окно не накладывается на предыдущее', async () => {
  const modal = createModalLifecycle()
  await modal.open()
  const next = vi.fn()
  const closed = modal.dismiss()
  const done = closed.then(next)
  await Promise.resolve()
  expect(next).not.toHaveBeenCalled()
  expect(modal.dismiss()).toBe(closed)
  modal.didDismiss()
  await done
  expect(next).toHaveBeenCalledOnce()
})
it('отмена не оставляет ожидание, а повторное открытие имеет собственное закрытие', async () => {
  const modal = createModalLifecycle()
  await modal.open()
  const first = modal.dismiss()
  const reopen = modal.open()
  modal.didDismiss()
  await first
  await reopen
  const second = modal.dismiss()
  expect(second).not.toBe(first)
  modal.didDismiss()
  await second
  await modal.dismiss()
})
it('закрытое окно и повторное событие закрытия не блокируют действия', async () => {
  const modal = createModalLifecycle()
  await modal.dismiss()
  modal.didDismiss()
  await modal.open()
  const done = modal.dismiss()
  modal.didDismiss()
  modal.didDismiss()
  await done
})
