import * as Haptics from 'expo-haptics'
import { useEffect, useState } from 'react'
import { Platform } from 'react-native'
import { usePanGesture } from 'react-native-gesture-handler'

/** Выбор дня нажатием или горизонтальным движением по области столбцов. */
export function useChartDaySelection(count: number, plotWidth: number) {
  const [selected, setSelected] = useState<number | null>(null)

  // Один отклик на новый день, а не на каждое движение пальца.
  useEffect(() => {
    if (selected === null || Platform.OS === 'web') return
    void Haptics.selectionAsync().catch(() => {
      // Отсутствие тактильного отклика не мешает выбору дня.
    })
  }, [selected])

  function selectAt(x: number) {
    if (!count || plotWidth <= 0 || !Number.isFinite(x)) return
    const index = Math.floor((x / plotWidth) * count)
    setSelected(Math.max(0, Math.min(count - 1, index)))
  }

  const gesture = usePanGesture({
    enabled: count > 0 && plotWidth > 0,
    disableReanimated: true,
    maxPointers: 1,
    // Горизонтально выбираем день; вертикально оставляем прокрутку страницы.
    activeOffsetX: [-6, 6],
    failOffsetY: [-10, 10],
    onActivate: event => selectAt(event.x),
    onUpdate: event => selectAt(event.x)
  })

  return { selected, selectAt, gesture }
}
