import AsyncStorage from '@react-native-async-storage/async-storage'
import { useEffect, useRef, useState } from 'react'

import type { ChartGrouping } from '../model/chartPoints'

const KEY = 'perk.chart-grouping'
const VALUES: ChartGrouping[] = ['day', 'week', 'month']

/** Выбор «Дни / Недели / Месяцы» сохраняется на устройстве и не зависит от периода. */
export function useChartGrouping() {
  const [grouping, setGrouping] = useState<ChartGrouping>('day')
  const changed = useRef(false)
  useEffect(() => {
    let active = true
    AsyncStorage.getItem(KEY)
      .then(value => {
        if (
          active &&
          !changed.current &&
          VALUES.includes(value as ChartGrouping)
        )
          setGrouping(value as ChartGrouping)
      })
      .catch(() => {})
    return () => {
      active = false
    }
  }, [])

  function change(value: ChartGrouping) {
    changed.current = true
    setGrouping(value)
    void AsyncStorage.setItem(KEY, value).catch(() => {})
  }

  return [grouping, change] as const
}
