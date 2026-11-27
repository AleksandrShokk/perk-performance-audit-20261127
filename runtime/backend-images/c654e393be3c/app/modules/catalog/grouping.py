"""Mirror marketplace groups within one store; explicit manual choices take priority."""


def group_cards(cards, overrides=None):
    overrides = overrides or {}
    groups = {}
    for card in sorted(cards, key=lambda item: item["nm_id"]):
        article = card["nm_id"]
        override = overrides.get(article)
        source_id = str(card.get("group_id") or "").strip()
        if override:
            key, basis, title = override["key"], "manual", override.get("title", "")
        elif (
            source_id.isascii()
            and source_id.isdecimal()
            and len(source_id) <= 32
            and int(source_id) > 0
        ):
            key, basis, title = f"marketplace:{int(source_id)}", "marketplace", ""
        else:
            key, basis, title = f"single:{article}", "single", ""
        group = groups.setdefault(key, dict(id=key, basis=basis, title=title, cards=[]))
        group["cards"].append(card)
    return list(groups.values())
