from decimal import Decimal

import httpx

from app.integrations.wildberries.data import Source, WBDataClient
from app.modules.catalog.grouping import group_cards
from app.modules.catalog.identity import ozon_identity
from app.modules.catalog.metadata import definitions
from app.modules.sync.normalize import normalize


def card(identifier, code, color="чёрный", model="Urban", group="100"):
    return dict(
        nm_id=identifier,
        vendor_code=code,
        brand="PERK",
        category_id="10",
        subject="Перчатки",
        type_id="",
        group_id=group,
        title="Мотоперчатки " + model,
        colors=[color],
        sizes=[dict(size="M")],
        attributes=[
            dict(id="1", name="Модель", values=[model]),
            dict(id="2", name="Тип защиты", values=["костяшки"]),
        ],
    )


def groups(*cards, **kwargs):
    return sorted(
        sorted(item["nm_id"] for item in group["cards"])
        for group in group_cards(list(cards), **kwargs)
    )


def test_same_marketplace_group_merges_different_colours_without_name_matching():
    assert groups(card("1", "A"), card("2", "UNRELATED", "красный", model="Other")) == [["1", "2"]]


def test_identical_models_in_different_source_groups_stay_separate():
    assert groups(card("1", "URBAN-BLACK"), card("2", "URBAN-RED", "красный", group="200")) == [
        ["1"],
        ["2"],
    ]


def test_source_group_is_preserved_even_if_models_or_other_characteristics_differ():
    first = card("1", "URBAN-BLACK")
    second = card("2", "URBAN-PRO", model="Urban Pro")
    second.update(brand="Other", category_id="99")
    second["attributes"][1]["values"] = ["без защиты"]
    assert groups(first, second) == [["1", "2"]]


def test_grouping_does_not_need_brand_category_title_or_characteristics():
    assert groups(dict(nm_id="1", group_id="10"), dict(nm_id="2", group_id=10)) == [["1", "2"]]


def test_missing_zero_or_invalid_group_ids_do_not_combine_unrelated_cards():
    for value in [None, "", 0, "0", "-1", "unknown", False, "1.5", "9" * 40]:
        assert groups(dict(nm_id="1", group_id=value), dict(nm_id="2", group_id=value)) == [
            ["1"],
            ["2"],
        ]


def test_manual_split_and_merge_override_source_group_and_survive_its_changes():
    first, second = card("1", "URBAN-BLACK"), card("2", "URBAN-RED", "красный")
    assert groups(first, second, overrides={"1": {"key": "manual:solo"}}) == [["1"], ["2"]]
    second["group_id"] = "999"
    assert groups(
        first, second, overrides={"1": {"key": "manual:group"}, "2": {"key": "manual:group"}}
    ) == [["1", "2"]]
    result = group_cards([first, second], {"1": {"key": "manual:solo", "title": "Мой товар"}})
    assert result[0]["basis"] == "manual" and result[0]["title"] == "Мой товар"


def test_group_ids_are_stable_and_namespaced_and_do_not_change_with_input_order():
    first, second = card("1", "A"), card("2", "B")
    a = group_cards([first, second])
    b = group_cards([second, first])
    assert a == b and a[0]["id"] == "marketplace:100" and a[0]["basis"] == "marketplace"
    first["group_id"] = None
    assert group_cards([first])[0]["id"] == "single:1"


def test_ozon_group_id_uses_the_same_common_grouping_without_model_inference():
    rows = [ozon_identity(dict(model_info={"model_id": 50}), {}) for _ in range(2)]
    rows[0]["nm_id"], rows[1]["nm_id"] = "1", "2"
    assert groups(*rows) == [["1", "2"]]


def test_normalization_keeps_group_photos_and_attributes_but_rejects_non_provider_urls():
    _, result = normalize(
        Source.CATALOG,
        dict(
            nmID=42,
            imtID=10,
            subjectID=7,
            characteristics=[
                dict(id=1, name="Материал", value=["кожа"]),
                dict(id=2, name="Длина", value=Decimal("12.00")),
            ],
            photos=[
                {"big": "https://basket-01.wbbasket.ru/item/photo.jpg"},
                {"big": "https://localhost/secret"},
                {"big": "file:///private"},
                {"big": "https://wbstatic.net.evil.test/x"},
            ],
        ),
    )
    assert result["group_id"] == "10" and result["category_id"] == "7"
    assert result["photos"] == ["https://basket-01.wbbasket.ru/item/photo.jpg"]
    assert result["attributes"][1]["values"] == ["12"]


def test_ozon_adapter_preserves_characteristic_definitions_and_images():
    result = ozon_identity(
        dict(
            model_info={"model_id": 100},
            description_category_id=1,
            type_id=2,
            primary_image="https://cdn1.ozone.ru/image.jpg",
            attributes=[{"id": 10, "values": [{"value": "черный"}]}],
        ),
        {"10": {"name": "Цвет", "is_aspect": True}},
    )
    assert result["marketplace"] == "ozon" and result["group_id"] == "100"
    assert result["attributes"][0]["variable"] is True
    assert result["attributes"][0]["values"] == ["черный"]


def test_category_definitions_use_fixed_provider_endpoint():
    requests = []

    def response(request):
        requests.append(request)
        return httpx.Response(
            200, json={"data": [{"charcID": 1, "name": "Размер", "isVariable": True}]}
        )

    client = WBDataClient(transport=httpx.MockTransport(response))
    rows = client.category_schema("synthetic-token", "42")
    assert requests[0].method == "GET"
    assert str(requests[0].url) == "https://content-api.wildberries.ru/content/v2/object/charcs/42"
    assert definitions(rows) == {"1": {"name": "Размер", "variable": True}}
