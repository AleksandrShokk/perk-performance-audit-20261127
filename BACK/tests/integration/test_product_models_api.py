from copy import deepcopy

from sqlalchemy import select
from sqlalchemy.orm import Session
from test_catalog import card, employee, seed, stock
from test_wb_sync_database import (
    owner_client as owner_client,
)
from test_wb_sync_database import (
    pytestmark as pytestmark,
)
from test_wb_sync_database import (
    setup as setup,
)

from app.db.session import set_actor
from app.integrations.wildberries.data import Source
from app.modules.catalog.models import CatalogOverride


def data():
    first = card("42", "URBAN-BLACK", "Мотоперчатки Urban")
    first.update(
        category_id="10",
        group_id="100",
        marketplace="wildberries",
        photos=[],
        attributes=[{"id": "1", "name": "Модель", "values": ["Urban"]}],
    )
    second = deepcopy(first)
    second.update(nm_id="43", vendor_code="URBAN-RED", colors=["красный"])
    pro = deepcopy(first)
    pro.update(
        nm_id="44",
        group_id="200",
        vendor_code="URBAN-PRO-BLACK",
        title="Мотоперчатки Urban Pro",
        attributes=[{"id": "1", "name": "Модель", "values": ["Urban Pro"]}],
    )
    return first, second, pro


def path(s):
    return f"/api/v1/workspaces/{s.workspace_id}/product-models"


def test_source_grouping_before_search_and_pagination_keeps_all_colours(setup, owner_client):
    s = setup
    cards = data()
    seed(s, Source.CATALOG, [(row["nm_id"], row) for row in cards])
    seed(s, Source.STOCKS, [("42:10:1", stock()), ("43:10:1", stock(article="43", quantity=4))])
    client, _ = owner_client
    response = client.get(path(s), params={"q": "URBAN-RED", "limit": 1})
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["total"] == 1 and value["total_products"] == 2
    assert {row["nm_id"] for row in value["items"][0]["products"]} == {"42", "43"}
    assert value["items"][0]["stock"] == 7
    assert client.get(path(s), params={"limit": 1}).json()["total"] == 2


def test_manual_split_and_merge_persist_and_are_store_scoped(setup, owner_client):
    s = setup
    cards = data()
    seed(s, Source.CATALOG, [(row["nm_id"], row) for row in cards])
    client, base = owner_client
    edit = base + "/product-grouping"
    assert client.post(edit, json={"articles": ["43"]}).status_code == 200
    assert client.get(path(s)).json()["total"] == 3
    assert client.post(edit, json={"articles": ["42", "43"], "title": "Urban"}).status_code == 200
    response = client.get(path(s)).json()
    assert response["total"] == 2
    model = next(row for row in response["items"] if len(row["products"]) == 2)
    assert model["title"] == "Urban" and model["grouping"] == "manual"
    assert client.post(edit, json={"articles": ["999"]}).status_code == 404
    assert client.post(edit, json={"articles": ["invalid"]}).status_code == 422


def test_employee_reads_groups_but_cannot_change_grouping_or_read_another_store(
    setup, owner_client
):
    s = setup
    cards = data()
    seed(s, Source.CATALOG, [(row["nm_id"], row) for row in cards])
    client, base = owner_client
    assert (
        client.post(base + "/product-grouping", json={"articles": ["42", "43"]}).status_code == 200
    )
    employee(s, ["inventory.read"], [str(s.store_id)])
    response = client.get(path(s))
    assert response.status_code == 200, response.text
    assert all(item["missing_cost_variants"] is None for item in response.json()["items"])
    assert client.post(base + "/product-grouping", json={"articles": ["43"]}).status_code == 404
    with Session(s.engine) as db, db.begin():
        set_actor(db, s.other_id)
        assert len(db.scalars(select(CatalogOverride)).all()) == 2


def test_group_override_cannot_be_written_directly_by_employee(setup, owner_client):
    import pytest
    from sqlalchemy.exc import DBAPIError

    s = setup
    employee(s, ["inventory.read"], [str(s.store_id)])
    with Session(s.engine) as db:
        set_actor(db, s.other_id)
        db.add(
            CatalogOverride(
                workspace_id=s.workspace_id,
                store_id=s.store_id,
                nm_id="42",
                model_key="manual:forbidden",
                ciphertext="invalid",
                created_by=s.other_id,
            )
        )
        with pytest.raises(DBAPIError):
            db.flush()
        db.rollback()


def test_manual_group_allows_user_choice_across_categories_but_rejects_unknown_store(
    setup, owner_client
):
    from uuid import uuid4

    s = setup
    first, second, _ = data()
    second["category_id"] = "99"
    seed(s, Source.CATALOG, [(row["nm_id"], row) for row in [first, second]])
    client, base = owner_client
    assert (
        client.post(base + "/product-grouping", json={"articles": ["42", "43"]}).status_code == 200
    )
    assert (
        client.post(
            base.replace(str(s.store_id), str(uuid4())) + "/product-grouping",
            json={"articles": ["42"]},
        ).status_code
        == 404
    )


def test_category_metadata_queue_reads_store_credential_by_scope(setup, monkeypatch):
    from unittest.mock import Mock

    from app.modules.catalog import tasks

    s = setup
    seed(s, Source.CATALOG, [("42", data()[0])])
    s.redis.get.return_value = None
    enqueue = Mock()
    monkeypatch.setattr(tasks, "resources", lambda: (s.settings, s.engine, s.redis, s.vault))
    monkeypatch.setattr(tasks.fetch_schema, "apply_async", enqueue)
    tasks.queue_schemas.run(str(s.workspace_id), str(s.store_id), str(s.user_id))
    enqueue.assert_called_once_with(
        args=[str(s.workspace_id), str(s.store_id), str(s.user_id), "10"], countdown=0, retry=False
    )


def test_category_metadata_fetch_uses_validated_credentials_and_caches_flags(setup, monkeypatch):
    from unittest.mock import Mock

    from app.modules.catalog import tasks

    s = setup
    s.redis.get.return_value = None
    client = Mock(cooldown_seconds=0)
    client.category_schema.return_value = [{"charcID": 1, "name": "Материал", "isVariable": False}]
    monkeypatch.setattr(tasks, "resources", lambda: (s.settings, s.engine, s.redis, s.vault))
    monkeypatch.setattr(tasks, "WBDataClient", lambda: client)
    tasks.fetch_schema.apply(
        args=[str(s.workspace_id), str(s.store_id), str(s.user_id), "10"], throw=True
    )
    client.category_schema.assert_called_once()
    assert client.category_schema.call_args.args[1] == "10"
    assert any(
        call.args[0] == tasks.schema_key("10") and "variable" in call.args[1]
        for call in s.redis.set.call_args_list
    )


def test_source_group_ignores_model_names_in_api_and_preserves_original_articles(
    setup, owner_client
):
    s = setup
    first, second, pro = data()
    pro["group_id"] = first["group_id"]
    seed(s, Source.CATALOG, [(row["nm_id"], row) for row in [first, second, pro]])
    client, _ = owner_client
    result = client.get(path(s), params={"q": "URBAN-PRO"}).json()
    assert result["total"] == 1 and result["total_products"] == 3
    assert result["items"][0]["grouping"] == "marketplace"
    assert {row["nm_id"] for row in result["items"][0]["products"]} == {"42", "43", "44"}


def test_same_marketplace_group_id_in_different_stores_never_merges(setup, owner_client):
    from uuid import uuid4

    from app.modules.accounts.models import Store

    s = setup
    other = uuid4()
    with Session(s.admin) as db, db.begin():
        db.add(
            Store(
                id=other,
                workspace_id=s.workspace_id,
                name="Other store",
                marketplace="wildberries",
                external_seller_id=str(uuid4()),
                connection_status="connected",
            )
        )
    first = data()[0]
    seed(s, Source.CATALOG, [("42", first)])
    seed(s, Source.CATALOG, [("42", first)], store_id=other)
    client, _ = owner_client
    result = client.get(path(s)).json()
    assert result["total"] == 2
    assert len({row["id"] for row in result["items"]}) == 2
    employee(s, ["inventory.read"], [str(s.store_id)])
    assert client.get(path(s)).json()["total"] == 1
