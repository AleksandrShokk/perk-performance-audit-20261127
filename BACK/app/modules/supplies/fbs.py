"""Only published seller stock, scoped to its own cabinet and product identity."""

from app.integrations.wildberries.data import Source
from app.modules.catalog.ozon_read import item, snapshot
from app.modules.sync.read import retained, source_states


def quantities(db, vault, wid, store):
    if store.marketplace == "ozon":
        rows, stamp = snapshot(db, vault, wid, store)
        return (
            {item(row, store, stamp, True).id: row["channels"]["fbs"]["quantity"] for row in rows}
            if rows is not None
            else None
        )
    state = source_states(db, wid, store.id, [Source.FBS])[Source.FBS]
    if not state.success:
        return None
    result = {}
    for row in retained(db, vault, wid, store.id, Source.FBS):
        result[row["nm_id"]] = result.get(row["nm_id"], 0) + row["quantity"]
    return result
