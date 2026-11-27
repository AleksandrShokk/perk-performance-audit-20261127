export type StoreFeature =
  | 'catalog'
  | 'inventory'
  | 'finance'
  | 'finance_details'
  | 'analytics'
  | 'supplies'
  | 'supply_history'
type Store = { marketplace: string; features?: readonly string[] }

export function supportsFeature(store: Store, feature: StoreFeature) {
  return (
    store.features?.includes(feature) ?? store.marketplace === 'wildberries'
  )
}

/** A partial WB report must never be presented as the combined WB + Ozon total. */
export function selectionSupports(
  stores: readonly Store[],
  feature: StoreFeature
) {
  return (
    stores.length > 0 && stores.every(store => supportsFeature(store, feature))
  )
}
