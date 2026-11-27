import type { ChartPoint } from './chartPoints'

type Position = { x: number; y: number }

/** Непрерывные участки. Не соединяем линией даты, для которых данных нет. */
export function chartSegments(
  points: ChartPoint[],
  x: (index: number) => number,
  y: (value: number) => number
) {
  const groups: Position[][] = []
  let current: Position[] = []
  for (const [index, point] of points.entries()) {
    if (point.value === null) {
      if (current.length) groups.push(current)
      current = []
    } else current.push({ x: x(index), y: y(point.value) })
  }
  if (current.length) groups.push(current)

  return groups.map(group => {
    const first = group[0]!
    const last = group[group.length - 1]!
    let line = `M${first.x},${first.y}`
    for (let index = 1; index < group.length; index += 1) {
      const previous = group[index - 1]!
      const next = group[index]!
      const middle = (previous.x + next.x) / 2
      line += ` C${middle},${previous.y} ${middle},${next.y} ${next.x},${next.y}`
    }
    return {
      line,
      area: `${line} L${last.x},${y(0)} L${first.x},${y(0)} Z`,
      isolated: group.length === 1 ? first : null
    }
  })
}
