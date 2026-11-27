"""Native warehouse scopes. Never split global demand by stock shares."""

from collections import defaultdict
from decimal import Decimal

from app.modules.insights.ozon_sales import integer as ozon_integer
from app.modules.insights.ozon_sales import number
from app.modules.inventory.stock_cover import order_rate
from app.modules.sync.normalize import integer, string


def wb_regions(data, start, end):
    # Root offices and nested size offices describe the same units. Use one level.
    sizes = data.get("sizes") or []
    nested = [(str(size["chrtID"]), office) for size in sizes for office in size.get("offices", [])]
    offices = nested or [("", office) for office in data.get("offices", [])]
    groups, seen, locations = {}, {}, {}
    for variant, office in offices:
        region = string(office["regionName"], 160).strip()
        if not region or region in {"Свой склад", "Свой склад СГТ"}:
            raise ValueError("Регион Wildberries не найден.")
        warehouse = str(integer(office["officeID"], signed=True))
        # Negative IDs and generic labels are WB aggregate buckets, not destinations.
        if int(warehouse) <= 0 or str(office.get("officeName", "")).casefold().strip().startswith(
            ("склад wb", "склады wb")
        ):
            continue
        key = variant, warehouse
        if key in seen:
            if seen[key] != office:
                raise ValueError("Данные о складе Wildberries противоречат друг другу.")
            continue
        seen[key] = office
        destination = "wb-office:" + warehouse
        office_name = str(office.get("officeName") or "").strip()
        name = office_name if office_name else "Склад WB " + warehouse
        if warehouse in locations and locations[warehouse] != destination:
            raise ValueError("Данные о регионе Wildberries противоречат друг другу.")
        locations[warehouse] = destination
        group = groups.setdefault(
            destination,
            {
                "id": destination,
                "name": name,
                "stock": 0,
                "daily_orders": Decimal(0),
                "warehouse_ids": set(),
            },
        )
        metrics = office["metrics"]
        missing = metrics.get("officeMissingTime")
        hours = None
        if missing is not None:
            days, rest = (
                integer(missing["days"], signed=True),
                integer(missing["hours"], signed=True),
            )
            if days >= 0 and 0 <= rest < 24 and days * 24 + rest <= (end - start).days * 24 + 24:
                hours = days * 24 + rest
        row = {
            "date_from": str(start),
            "date_to": str(end),
            "missing_hours": hours,
            "orders": integer(metrics["ordersCount"])
            if metrics.get("ordersCount") is not None
            else None,
        }
        rate = Decimal(0) if row["orders"] == 0 else order_rate(row)
        stock = integer(metrics["stockCount"]) if metrics.get("stockCount") is not None else None
        group["stock"] = (
            group["stock"] + stock if group["stock"] is not None and stock is not None else None
        )
        group["daily_orders"] = (
            group["daily_orders"] + rate
            if group["daily_orders"] is not None and rate is not None
            else None
        )
        group["warehouse_ids"].add(warehouse)
    return [
        {
            **group,
            "warehouse_ids": sorted(group["warehouse_ids"]),
            "daily_orders": str(group["daily_orders"])
            if group["daily_orders"] is not None
            else None,
        }
        for group in groups.values()
    ]


def ozon_clusters(rows):
    groups = defaultdict(dict)
    for row in rows:
        sku = str(ozon_integer(row["sku"], positive=True))
        raw = row.get("cluster_id")
        if raw is None or isinstance(raw, bool) or not str(raw).isdigit() or int(raw) <= 0:
            continue
        cluster = str(raw)
        group = groups[sku].setdefault(
            cluster,
            {
                "id": cluster,
                "name": "",
                "stock": 0,
                "rates": set(),
                "warehouses": {},
                "warehouse_ids": set(),
            },
        )
        name = row.get("cluster_name")
        if isinstance(name, str) and 0 < len(name.strip()) <= 160:
            group["name"] = name.strip()
        warehouse = str(row["warehouse_id"])
        key = warehouse, str(row.get("placement_zone", ""))
        stock = ozon_integer(row["available_stock_count"])
        try:
            rate = number(row.get("ads_cluster"))
        except ValueError, ArithmeticError, TypeError:
            rate = None
        group["rates"].add(str(rate.normalize()) if rate is not None else None)
        if key in group["warehouses"]:
            if group["warehouses"][key] != stock:
                raise ValueError("Данные об остатках кластера противоречат друг другу.")
            continue
        group["warehouses"][key] = stock
        group["warehouse_ids"].add(warehouse)
        # ads_cluster is repeated for warehouses, just as global ads is repeated.
    return {
        sku: [
            {
                "id": cluster,
                "name": g["name"] or f"Кластер {cluster}",
                "stock": sum(g["warehouses"].values()),
                "warehouse_ids": sorted(g["warehouse_ids"]),
                "daily_orders": next(iter(g["rates"])) if len(g["rates"]) == 1 else None,
            }
            for cluster, g in clusters.items()
        ]
        for sku, clusters in groups.items()
    }
