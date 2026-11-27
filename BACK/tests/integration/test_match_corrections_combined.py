from uuid import uuid4

from test_beta_catalog_imports import base, seed_pair
from test_catalog import employee
from test_wb_sync_database import owner_client as owner_client
from test_wb_sync_database import pytestmark as pytestmark
from test_wb_sync_database import setup as setup

from app.modules.catalog.import_service import MATCH_HEADERS
from app.modules.finance.xlsx import build_template, read_rows


def test_manual_error_file_can_be_corrected_and_reuploaded_without_losing_valid_rows(
    setup, owner_client
):
    s = setup
    client, _ = owner_client
    sid = seed_pair(s)
    root = base(s) + "/catalog/matches"
    pair = {"left_store_id": str(s.store_id), "right_store_id": str(sid)}
    original = [
        ["GLOVE", "001", "Article-1", "001"],
        ["GLOVE", "002", "unknown", "002"],
    ]
    file = build_template(MATCH_HEADERS, original, sheet_name="Соответствия")
    preview = client.post(root + "/preview", params=pair, files={"file": ("matches.xlsx", file)})
    assert preview.status_code == 200, preview.text
    assert not preview.json()["can_apply"]
    response = client.post(
        root + "/corrections", params=pair, files={"file": ("matches.xlsx", file)}
    )
    assert response.status_code == 200, response.text
    assert "no-store" in response.headers["cache-control"]
    rows = read_rows(response.content, headers=MATCH_HEADERS, sheet_name="Соответствия")
    assert [cells for _, cells in rows] == original
    errors = read_rows(
        response.content,
        headers=("Строка на листе Соответствия", "Что исправить"),
        sheet_name="Ошибки",
    )
    assert errors[0][1][0] == "3"
    fixed = [cells for _, cells in rows]
    fixed[1][2] = "Article-2"
    result = client.post(
        root + "/preview",
        params=pair,
        files={
            "file": (
                "fixed.xlsx",
                build_template(MATCH_HEADERS, fixed, sheet_name="Соответствия"),
            )
        },
    ).json()
    assert result["can_apply"] and result["valid_count"] == 2, result
    saved = client.post(root + f"/{result['preview_id']}/apply", json=pair)
    assert saved.status_code == 200, saved.text
    assert client.get(root, params=pair).json()["count"] == 2
    remaining = client.get(root + "/unmatched", params=pair)
    assert remaining.status_code == 200, remaining.text
    assert read_rows(remaining.content, headers=MATCH_HEADERS, sheet_name="Соответствия") == []


def test_unmatched_export_keeps_both_sides_without_inventing_pairs_and_scopes_preview(
    setup, owner_client
):
    s = setup
    client, _ = owner_client
    sid = seed_pair(s)
    root = base(s) + "/catalog/matches"
    pair = {"left_store_id": str(s.store_id), "right_store_id": str(sid)}
    result = client.get(root + "/unmatched", params=pair)
    assert result.status_code == 200, result.text
    rows = read_rows(result.content, headers=MATCH_HEADERS, sheet_name="Соответствия")
    assert len(rows) == 4
    assert all(bool(cells[0]) != bool(cells[2]) for _, cells in rows)
    assert (
        client.get(root + "/unmatched", params={**pair, "preview_id": str(uuid4())}).status_code
        == 404
    )
    preview = client.post(root + "/automatic", json=pair).json()
    draft = client.get(root + "/unmatched", params={**pair, "preview_id": preview["preview_id"]})
    assert draft.status_code == 200, draft.text
    rows = read_rows(draft.content, headers=MATCH_HEADERS, sheet_name="Соответствия")
    assert len(rows) == 2 and all(cells[0] and cells[2] for _, cells in rows)
    assert (
        client.get(root + "/unmatched", params={**pair, "left_store_id": str(uuid4())}).status_code
        == 404
    )


def test_saved_matches_combine_only_the_general_catalog_before_search_and_pagination(
    setup, owner_client
):
    s = setup
    client, _ = owner_client
    sid = seed_pair(s)
    root = base(s) + "/catalog/matches"
    models = base(s) + "/product-models"
    pair = {"left_store_id": str(s.store_id), "right_store_id": str(sid)}
    assert client.get(models, params={"combine_marketplaces": True}).json()["total"] == 2
    preview = client.post(root + "/automatic", json=pair).json()
    assert client.post(root + f"/{preview['preview_id']}/apply", json=pair).status_code == 200
    combined = client.get(models, params={"combine_marketplaces": True, "limit": 1})
    assert combined.status_code == 200, combined.text
    page = combined.json()
    assert page["total"] == 1 and page["total_products"] == 3
    model = page["items"][0]
    assert model["combined"] and model["marketplace"] == "combined"
    assert {p["store_id"] for p in model["products"]} == {str(s.store_id), str(sid)}
    searched = client.get(models, params={"combine_marketplaces": True, "q": "Article-1"}).json()
    assert searched["total"] == 1 and len(searched["items"][0]["products"]) == 3
    assert client.get(models, params={"combine_marketplaces": False}).json()["total"] == 2
    single = client.get(
        models, params={"store_id": str(s.store_id), "combine_marketplaces": True}
    ).json()
    assert single["total"] == 1 and not single["items"][0]["combined"]
    for match in client.get(root, params=pair).json()["items"]:
        assert client.delete(root + "/" + match["id"]).status_code == 200
    assert client.get(models, params={"combine_marketplaces": True}).json()["total"] == 2


def test_combined_cards_and_correction_files_respect_employee_store_access(setup, owner_client):
    s = setup
    client, _ = owner_client
    sid = seed_pair(s)
    root = base(s) + "/catalog/matches"
    pair = {"left_store_id": str(s.store_id), "right_store_id": str(sid)}
    preview = client.post(root + "/automatic", json=pair).json()
    assert client.post(root + f"/{preview['preview_id']}/apply", json=pair).status_code == 200
    employee(s, ["inventory.read"], [str(s.store_id)])
    response = client.get(base(s) + "/product-models", params={"combine_marketplaces": True})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total"] == 1
    assert not data["items"][0]["combined"]
    assert all(p["store_id"] == str(s.store_id) for p in data["items"][0]["products"])
    assert client.get(root + "/unmatched", params=pair).status_code == 404
    file = build_template(
        MATCH_HEADERS, [["GLOVE", "001", "Article-1", "001"]], sheet_name="Соответствия"
    )
    assert (
        client.post(
            root + "/corrections", params=pair, files={"file": ("file.xlsx", file)}
        ).status_code
        == 404
    )
