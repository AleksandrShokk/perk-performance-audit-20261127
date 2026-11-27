"""Fixed read-only Seller API methods. Bounded responses, cursors and pagination.

Each complete import is published atomically. An incomplete response never erases
the previous successful snapshot. Money is parsed as Decimal, not binary float.
"""

from app.integrations.ozon.transport import OzonImportError as ImportError
from app.integrations.ozon.transport import SellerReader

LIST = "/v3/product/list"
INFO = "/v3/product/info/list"
ATTRIBUTES = "/v4/product/info/attributes"
STOCKS = "/v4/product/info/stocks"
PRICES = "/v5/product/info/prices"
DEFINITIONS = "/v1/description-category/attribute"
METHODS = frozenset({LIST, INFO, ATTRIBUTES, STOCKS, PRICES, DEFINITIONS})
BATCH = 1000
MAX_PRODUCTS = 100000


class CatalogClient(SellerReader):
    allowed_methods = METHODS

    def paged(self, path, body, *, result=False, cursor="cursor"):
        token, seen, count = "", set(), 0
        expected = None
        for _ in range(MAX_PRODUCTS // BATCH + 2):
            data = self.read(path, {**body, cursor: token, "limit": BATCH})
            container = data["result"] if result else data
            rows = container if isinstance(container, list) else container.get("items")
            if not isinstance(rows, list):
                raise ImportError("ozon_invalid_response")
            metadata = data if isinstance(container, list) else container
            # total is being retired by Ozon; prefer total_items when supplied.
            total = metadata.get("total_items", metadata.get("total"))
            if total is not None:
                if not isinstance(total, int) or total < 0 or total > MAX_PRODUCTS:
                    raise ImportError("ozon_catalog_limit")
                expected = total
            count += len(rows)
            if count > MAX_PRODUCTS:
                raise ImportError("ozon_catalog_limit")
            yield from rows
            next_token = metadata.get(cursor, "")
            if not rows or not next_token or expected is not None and count >= expected:
                if expected is not None and count < expected:
                    raise ImportError("ozon_incomplete_response")
                return
            next_token = str(next_token)
            if next_token == token or next_token in seen:
                raise ImportError("ozon_cursor_repeated")
            seen.add(next_token)
            token = next_token
        raise ImportError("ozon_catalog_limit")

    def fetch(self, normalize, progress=lambda count: None):
        with self:
            return self.fetch_all(normalize, progress)

    def fetch_all(self, normalize, progress):
        try:
            listings = list(
                self.paged(LIST, {"filter": {"visibility": "ALL"}}, result=True, cursor="last_id")
            )
            ids = [str(row["product_id"]) for row in listings]
            if len(ids) != len(set(ids)):
                raise ImportError("ozon_catalog_changed", 60)
            definitions, output = {}, []
            for start in range(0, len(ids), BATCH):
                batch = ids[start : start + BATCH]
                info = self.read(INFO, {"product_id": batch})["items"]
                details = list(
                    self.paged(
                        ATTRIBUTES,
                        {"filter": {"product_id": batch, "visibility": "ALL"}},
                        result=True,
                        cursor="last_id",
                    )
                )
                stock = list(
                    self.paged(STOCKS, {"filter": {"product_id": batch, "visibility": "ALL"}})
                )
                prices = list(
                    self.paged(PRICES, {"filter": {"product_id": batch, "visibility": "ALL"}})
                )
                indexes = []
                for position, (rows, field) in enumerate(
                    (
                        (info, "id"),
                        (details, "id"),
                        (stock, "product_id"),
                        (prices, "product_id"),
                    )
                ):
                    index = {str(row[field]): row for row in rows}
                    if (
                        len(index) != len(rows)
                        or not set(index) <= set(batch)
                        or position in {0, 2}
                        and set(index) != set(batch)
                    ):
                        raise ImportError("ozon_incomplete_response")
                    # Optional metadata may be unavailable for unpublished products.
                    # Identity and stock responses must still be complete.
                    for pid in batch:
                        if position == 1:
                            index.setdefault(pid, {"id": pid, "attributes": []})
                        elif position == 3:
                            index.setdefault(pid, {"product_id": pid, "price": {}})
                    indexes.append(index)
                for pid in batch:
                    item = indexes[0][pid]
                    category = (item.get("description_category_id"), item.get("type_id"))
                    schema = {}
                    if indexes[1][pid].get("attributes") and all(category):
                        if category not in definitions:
                            definitions[category] = self.attribute_definitions(category)
                        schema = definitions[category]
                    output.append(normalize(*(index[pid] for index in indexes), schema))
                progress(len(output))
            return output
        except KeyError, TypeError, ValueError, ArithmeticError:
            raise ImportError("ozon_invalid_response") from None

    def attribute_definitions(self, category):
        values = self.read(
            DEFINITIONS,
            {
                "description_category_id": category[0],
                "type_id": category[1],
                "language": "RU",
            },
        )["result"]
        return {str(row["id"]): row["name"] for row in values}
