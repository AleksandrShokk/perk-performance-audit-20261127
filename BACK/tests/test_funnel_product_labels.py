from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

from app.modules.insights import product_labels
from app.modules.insights.product_labels import labels


def test_neutral_wb_labels_preserve_barcodes_and_exclude_private_values():
    value = labels(
        [
            {
                "nm_id": "42",
                "title": "Helmet",
                "vendor_code": "A",
                "photos": ["photo"],
                "sizes": [{"barcodes": ["00042", "00042"]}],
                "unit_cost": "secret",
            }
        ],
        "wildberries",
    )
    assert value["42"] == {
        "title": "Helmet",
        "vendor_code": "A",
        "photos": ["photo"],
        "barcodes": ["00042"],
    }


def test_ozon_matches_sku_aliases_not_product_id_or_article():
    rows = [
        {
            "external_id": "42",
            "marketplace_code": "9001",
            "sku_aliases": ["9001", "9002"],
            "vendor_code": "9003",
            "title": "Boots",
            "barcodes": ["0001"],
        }
    ]
    value = labels(rows, "ozon")
    assert set(value) == {"9001", "9002"}
    assert "42" not in value and "9003" not in value


def test_ambiguous_sku_is_not_joined_to_the_wrong_product():
    assert (
        labels(
            [{"sku_aliases": ["9001"], "title": "A"}, {"sku_aliases": ["9001"], "title": "B"}],
            "ozon",
        )
        == {}
    )


def test_enrichment_is_scoped_and_does_not_mutate_metrics_or_native_ids(monkeypatch):
    calls = []

    def retained(db, vault, wid, sid, source):
        calls.append((wid, sid))
        return [{"nm_id": "42", "title": f"Store {sid}", "sizes": []}]

    monkeypatch.setattr(product_labels, "retained", retained)
    source = [{"nm_id": "42", "orders": 3}]
    result = product_labels.enrich(
        source, MagicMock(execute=Mock(return_value=[])), None, "workspace", "first", "wildberries"
    )
    assert result[0]["title"] == "Store first" and result[0]["orders"] == 3
    assert source == [{"nm_id": "42", "orders": 3}]
    assert calls == [("workspace", "first")]


def test_absent_ozon_catalog_does_not_hide_analytics():
    db = SimpleNamespace(get=lambda model, key: None)
    source = [{"nm_id": "", "marketplace_code": "9001", "orders": 3}]
    assert product_labels.enrich(source, db, None, "workspace", "store", "ozon") == source


def test_ozon_primary_and_channel_skus_work_without_sources():
    value = labels(
        [
            {
                "marketplace_code": "9001",
                "channel_skus": {"fbo": ["9002"], "fbs": ["9003"]},
                "title": "Helmet",
            }
        ],
        "ozon",
    )
    assert set(value) == {"9001", "9002", "9003"}
