from datetime import date
from decimal import Decimal

from app.integrations.wildberries.data import Source
from app.modules.catalog.service import variant_price
from app.modules.finance.report import PriceBook
from app.modules.sync.normalize import normalize


def test_aliases_with_conflicting_prices_stay_unknown_and_a_zero_cost_is_known():
    book = PriceBook(
        {
            ("42", "001", "RUB"): [(date(2025, 1, 1), Decimal("10"))],
            ("42", "alias", "RUB"): [(date(2025, 1, 1), Decimal("20"))],
        }
    )
    assert variant_price(book, "42", ["001", "alias"], "RUB", "2026-01-01") is None
    assert (
        variant_price(
            PriceBook({("42", "", "RUB"): [(date(2025, 1, 1), Decimal("0"))]}),
            "42",
            ["001", "alias"],
            "RUB",
            "2026-01-01",
        )
        == "0"
    )
    assert variant_price(book, "42", ["001"], "USD", "2026-01-01") is None


def test_color_names_are_saved_without_other_arbitrary_characteristics():
    _, result = normalize(
        Source.CATALOG,
        {
            "nmID": 42,
            "characteristics": [
                {"name": "Цвет", "value": ["чёрный", "чёрный", "красный"]},
                {"name": "ignored", "value": "private"},
            ],
        },
    )
    assert result["colors"] == ["чёрный", "красный"]
    assert "characteristics" not in result
