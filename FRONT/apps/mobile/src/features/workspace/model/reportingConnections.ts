type Connection = {
  marketplace: string
  reports_available?: boolean
  features?: readonly string[]
}

/** A store becomes selectable when at least its catalog is supported. */
export function reportingConnections<T extends Connection>(
  connections: readonly T[]
): T[] {
  return connections.filter(
    store =>
      store.features?.includes('catalog') ||
      (store.reports_available ?? store.marketplace === 'wildberries')
  )
}
