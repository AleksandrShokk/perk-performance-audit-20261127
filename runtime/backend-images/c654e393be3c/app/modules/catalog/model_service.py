import json
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert

from app.db.tenant import scope
from app.integrations.wildberries.data import Source
from app.modules.accounts.models import Store
from app.modules.catalog.grouping import group_cards
from app.modules.catalog.models import CatalogOverride
from app.modules.catalog.schemas import ProductModel, ProductModelsPage
from app.modules.catalog.service import matches, products
from app.modules.sync.read import retained


def override_aad(workspace_id, store_id, article):
    return f"perk-catalog-group:v1:{workspace_id}:{store_id}:{article}"


def overrides(db, vault, workspace_id, store_id):
    result = {}
    for row in db.scalars(
        select(CatalogOverride).where(*scope(CatalogOverride, workspace_id, store_id))
    ):
        payload = json.loads(
            vault.open(row.ciphertext, override_aad(workspace_id, store_id, row.nm_id))
        )
        result[row.nm_id] = {"key": row.model_key, "title": payload.get("title", "")}
    return result


def model_page(
    db,
    vault,
    workspace_id,
    stores,
    currency,
    query,
    in_stock,
    missing_cost,
    can_stock,
    can_cost,
    limit,
    offset,
    combine_marketplaces=False,
):
    identities = {}
    atomic = products(
        db,
        vault,
        workspace_id,
        stores,
        currency,
        "",
        False,
        False,
        can_stock,
        can_cost,
        None,
        0,
        identities,
    )
    indexed = {
        (str(item.store_id), item.nm_id): item
        for item in atomic.items
        if item.marketplace == "wildberries"
    }
    result = []
    for store in stores:
        if store.marketplace == "ozon":
            from app.modules.catalog.ozon_read import models

            result.extend(
                models(
                    db,
                    vault,
                    workspace_id,
                    store,
                    "" if combine_marketplaces else query,
                    False if combine_marketplaces else in_stock,
                    False if combine_marketplaces else missing_cost,
                    can_stock,
                    can_cost,
                    currency,
                )
            )
            continue
        cards = [card for (sid, _), card in identities.items() if sid == str(store.id)]
        grouped = group_cards(cards, overrides(db, vault, workspace_id, store.id))
        for group in grouped:
            # Search selects the entire marketplace card, including all its variants.
            if not combine_marketplaces and not any(
                matches(card, query) for card in group["cards"]
            ):
                continue
            members = [indexed[(str(store.id), card["nm_id"])] for card in group["cards"]]
            stock = (
                sum(item.stock for item in members)
                if all(item.stock is not None for item in members)
                else None
            )
            missing = sum(item.missing_cost_variants for item in members) if can_cost else None
            if not combine_marketplaces and in_stock and not stock:
                continue
            if not combine_marketplaces and missing_cost and not missing:
                continue
            result.append(
                ProductModel(
                    id=f"{store.id}:{group['id']}",
                    store_id=store.id,
                    store_name=store.name,
                    marketplace=store.marketplace,
                    title=group["title"] or members[0].title,
                    brand=members[0].brand,
                    grouping=group["basis"],
                    products=members,
                    stock=stock,
                    missing_cost_variants=missing,
                )
            )
    if combine_marketplaces:
        from app.modules.catalog.combined_models import combine, matches_model

        result = [
            model
            for model in combine(db, workspace_id, stores, result)
            if matches_model(model, query)
            and (not in_stock or any(p.stock for p in model.products))
            and (not missing_cost or model.missing_cost_variants)
        ]
    result.sort(key=lambda model: (model.title.casefold(), str(model.store_id), model.id))
    return ProductModelsPage(
        items=result[offset : offset + limit],
        total=len(result),
        total_products=sum(len(item.products) for item in result),
        total_variants=sum(len(product.variants) for item in result for product in item.products),
        currency=currency,
        limit=limit,
        offset=offset,
        is_loading=atomic.is_loading,
        is_partial=atomic.is_partial,
        error_code=atomic.error_code,
    )


def assign(db, vault, workspace_id, store_id, actor, data):
    articles = sorted(set(data.articles))
    store = db.get(Store, store_id)
    if store.marketplace == "ozon":
        from app.modules.catalog.ozon_read import snapshot

        source, _ = snapshot(db, vault, workspace_id, store)
        cards = {row["external_id"]: row for row in source or [] if row["external_id"] in articles}
    else:
        cards = {
            card["nm_id"]: card
            for card in retained(db, vault, workspace_id, store_id, Source.CATALOG)
            if card["nm_id"] in articles
        }
    if len(cards) != len(articles):
        raise HTTPException(404, "Товар не найден в этом магазине.")
    if data.action == "reset":
        db.execute(
            delete(CatalogOverride).where(
                *scope(CatalogOverride, workspace_id, store_id),
                CatalogOverride.nm_id.in_(articles),
            )
        )
        return "marketplace"
    model_key = "manual:" + str(uuid4())
    for article in articles:
        stmt = insert(CatalogOverride).values(
            workspace_id=workspace_id,
            store_id=store_id,
            nm_id=article,
            model_key=("manual:" + str(uuid4())) if data.action == "split" else model_key,
            ciphertext=vault.seal(
                json.dumps({"title": data.title.strip()}),
                override_aad(workspace_id, store_id, article),
            ),
            created_by=actor,
        )
        db.execute(
            stmt.on_conflict_do_update(
                index_elements=["workspace_id", "store_id", "nm_id"],
                set_={
                    "model_key": stmt.excluded.model_key,
                    "ciphertext": stmt.excluded.ciphertext,
                    "created_by": actor,
                    "updated_at": func.now(),
                },
            )
        )
    return model_key
