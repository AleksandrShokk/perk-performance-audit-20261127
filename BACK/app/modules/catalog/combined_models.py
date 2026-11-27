"""Join native marketplace cards using saved variant matches, before filtering or pagination."""

from collections import defaultdict
from hashlib import sha256

from sqlalchemy import select

from app.modules.catalog.match_models import ProductMatch
from app.modules.catalog.schemas import ProductModel


def matches_model(model, query):
    words = query.casefold().split()
    for product in model.products:
        text = " ".join(
            [
                product.title,
                product.brand,
                product.subject,
                product.vendor_code,
                product.nm_id,
                product.external_id,
                product.marketplace_code,
                *product.colors,
                *[v.size for v in product.variants],
                *[code for v in product.variants for code in v.barcodes],
            ]
        ).casefold()
        if all(word in text for word in words):
            return True
    return False


def combine(db, workspace_id, stores, models):
    visible = {store.id for store in stores}
    owners = {
        variant.id: index
        for index, model in enumerate(models)
        for product in model.products
        for variant in product.variants
    }
    parents = list(range(len(models)))

    def root(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    for match in db.scalars(
        select(ProductMatch).where(
            ProductMatch.workspace_id == workspace_id,
            ProductMatch.left_store_id.in_(visible),
            ProductMatch.right_store_id.in_(visible),
        )
    ):
        left, right = (
            owners.get(str(match.left_variant_id)),
            owners.get(str(match.right_variant_id)),
        )
        if left is not None and right is not None:
            parents[root(right)] = root(left)
    groups = defaultdict(list)
    for index, model in enumerate(models):
        groups[root(index)].append(model)
    result = []
    for members in groups.values():
        if len(members) == 1:
            result.extend(members)
            continue
        members.sort(key=lambda model: (model.marketplace != "wildberries", model.id))
        products = [product for model in members for product in model.products]
        anchor = members[0]
        signature = "|".join(sorted(model.id for model in members))
        result.append(
            ProductModel(
                id="matched:" + sha256(signature.encode()).hexdigest()[:24],
                store_id=anchor.store_id,
                store_name=" · ".join(dict.fromkeys(p.store_name for p in products)),
                marketplace="combined",
                title=anchor.title,
                brand=anchor.brand,
                grouping="matched",
                combined=True,
                products=products,
                stock=sum(p.stock for p in products)
                if all(p.stock is not None for p in products)
                else None,
                missing_cost_variants=sum(p.missing_cost_variants for p in products)
                if all(p.missing_cost_variants is not None for p in products)
                else None,
            )
        )
    return result
