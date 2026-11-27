"""Public category definitions; seller values stay encrypted in WBRecord."""

import json


def schema_key(category):
    return f"perk-catalog-schema:wb:v1:{category}"


def cached_definitions(redis, categories):
    result = {}
    for category in categories:
        if not str(category).isdigit():
            continue
        raw = redis.get(schema_key(category))
        if not isinstance(raw, (str, bytes)) or len(raw) > 512000:
            continue
        try:
            values = json.loads(raw)
            if isinstance(values, dict):
                result[category] = values
        except ValueError, TypeError:
            pass
    return result


def definitions(rows):
    result = {}
    for row in rows[:500]:
        if not isinstance(row, dict):
            continue
        identifier = str(row.get("charcID", ""))
        if identifier.isdigit() and isinstance(row.get("isVariable"), bool):
            result[identifier] = {
                "variable": row["isVariable"],
                "name": str(row.get("name", ""))[:500],
            }
    return result
