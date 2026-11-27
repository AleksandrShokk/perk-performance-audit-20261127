"""Marketplace adapters. Identifiers remain source-specific; grouping uses normalized evidence."""

import re
import unicodedata
from decimal import Decimal
from urllib.parse import urlparse


def text(value):
    return " ".join(
        re.findall(r"[\w]+", unicodedata.normalize("NFKC", str(value)).casefold().replace("ё", "е"))
    )


def photos(values, marketplace):
    suffixes = (
        (".wbbasket.ru", ".wbstatic.net", ".wildberries.ru")
        if marketplace == "wildberries"
        else (".ozone.ru", ".ozon.ru")
    )
    result = []
    for value in values[:20]:
        if not isinstance(value, str) or len(value) > 2048:
            continue
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower()
        if (
            parsed.scheme == "https"
            and not parsed.username
            and any(host.endswith(suffix) for suffix in suffixes)
        ):
            if value not in result:
                result.append(value)
    return result


def attributes(values):
    result = []
    if not isinstance(values, list):
        return result
    for value in values[:500]:
        if not isinstance(value, dict):
            continue
        name = value.get("name", "")
        if not isinstance(name, str) or not name or len(name) > 500:
            continue
        raw = value.get("value", value.get("values", []))
        raw = raw if isinstance(raw, list) else [raw]
        parsed = []
        for cell in raw[:30]:
            if isinstance(cell, dict):
                cell = cell.get("value", "")
            if isinstance(cell, (int, float, Decimal)) and not isinstance(cell, bool):
                number = Decimal(str(cell))
                if not number.is_finite() or not -20 <= number.as_tuple().exponent <= 100:
                    continue
                cell = format(number.normalize(), "f")
            if isinstance(cell, str) and len(cell) <= 1000:
                parsed.append(str(cell))
        result.append(
            dict(
                id=str(value.get("id", "")),
                name=name,
                values=parsed,
                variable=value.get("variable") if isinstance(value.get("variable"), bool) else None,
            )
        )
    return result


def wb_identity(row):
    images = []
    for image in (row.get("photos") or [])[:20]:
        if isinstance(image, dict):
            images.append(image.get("c246x328") or image.get("tm") or image.get("big"))
    return dict(
        marketplace="wildberries",
        group_id=str(row.get("imtID") or ""),
        category_id=str(row.get("subjectID") or ""),
        type_id="",
        photos=photos(images, "wildberries"),
        attributes=attributes(row.get("characteristics", [])),
    )


def ozon_identity(row, definitions):
    """Prepared adapter for the Seller API attribute response; no Ozon requests are made here."""
    values = []
    for attribute in row.get("attributes", []):
        definition = definitions.get(str(attribute.get("id")), {})
        values.append(
            dict(
                id=str(attribute.get("id", "")),
                name=definition.get("name", ""),
                variable=definition.get("is_aspect"),
                values=attribute.get("values", []),
            )
        )
    return dict(
        marketplace="ozon",
        group_id=str(row.get("model_info", {}).get("model_id") or ""),
        category_id=str(row.get("description_category_id") or ""),
        type_id=str(row.get("type_id") or ""),
        photos=photos(
            [
                row.get("primary_image"),
                *(
                    image.get("file_name") if isinstance(image, dict) else image
                    for image in row.get("images", [])
                ),
            ],
            "ozon",
        ),
        attributes=attributes(values),
    )
