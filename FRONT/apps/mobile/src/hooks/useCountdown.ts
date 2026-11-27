import { useEffect, useState } from 'react'

/** Обратный отсчёт в секундах, например до повторной отправки кода. */
export function useCountdown(initialSeconds = 0) {
  const [deadline, setDeadline] = useState(
    () => Date.now() + initialSeconds * 1000
  )
  const [now, setNow] = useState(() => Date.now())
  const remaining = Math.max(0, Math.ceil((deadline - now) / 1000))

  useEffect(() => {
    if (remaining === 0) return
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [remaining])

  function restart(seconds: number) {
    const current = Date.now()
    setNow(current)
    setDeadline(current + seconds * 1000)
  }

  return { remaining, restart }
}
