from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.integrations.wildberries.data import Source
from app.modules.insights import buyouts
from app.modules.sync.analytics import METRIC_FORMAT, contribution, sale_date_contribution


def finance_row(**changes):
    return {
        "rrd_id": "1",
        "nm_id": "42",
        "operation": "Продажа",
        "document_type": "Продажа",
        "quantity": 2,
        "report_date": "2026-03-09",
        "sale_date": "2026-03-01T12:00:00",
        "currency": "RUB",
        "retail_amount": "300.00",
        **changes,
    }


def test_report_sale_is_also_counted_on_its_sale_date():
    key, values = sale_date_contribution(Source.FINANCE, finance_row())
    assert key == (date(2026, 3, 1), "42", "RUB")
    assert values["report_bydate_sales"] == 2
    assert values["report_bydate_sales_amount"] == Decimal("300.00")
    assert values["report_bydate_missing_dates"] == 0
    # The report-date aggregate is unchanged and keeps its own day.
    assert contribution(Source.FINANCE, finance_row())[0][0] == date(2026, 3, 9)
    returned = finance_row(operation="Возврат", document_type="Возврат", quantity=1)
    assert sale_date_contribution(Source.FINANCE, returned)[1]["report_bydate_returns"] == 1


def test_service_rows_and_missing_sale_dates():
    assert sale_date_contribution(Source.FINANCE, finance_row(operation="Логистика")) is None
    assert sale_date_contribution(Source.SALES, {"kind": "sale"}) is None
    key, values = sale_date_contribution(Source.FINANCE, finance_row(sale_date=None))
    assert key[0] == date(2026, 3, 9) and values["report_bydate_missing_dates"] == 1


def test_report_days_need_reports_after_the_day():
    yesterday = date(2026, 10, 22)
    windows = [{"date_from": "2026-01-01", "date_to": "2026-06-30"}]
    days = buyouts.report_days(windows, date(2026, 5, 25), date(2026, 6, 30), yesterday)
    assert date(2026, 5, 31) in days  # reports run 30 days past it
    assert date(2026, 6, 1) not in days  # late sales of June 1+ may still be unreported
    recent = [{"date_from": "2026-01-01", "date_to": "2026-10-22"}]
    assert date(2026, 10, 20) in buyouts.report_days(
        recent, date(2026, 10, 20), date(2026, 10, 20), yesterday
    )


def fake(monkeypatch, *, sales_known, finance_windows, data, format_version=METRIC_FORMAT):
    monkeypatch.setattr(buyouts, "known_days", lambda *args: sales_known)
    monkeypatch.setattr(buyouts, "coverage", lambda *args: {Source.FINANCE: finance_windows})
    monkeypatch.setattr(buyouts, "moscow_today", lambda: date(2026, 10, 23))

    def rows(db, vault, workspace_id, store_id, source, start, end):
        for day, nm_id, currency, values in data[source]:
            if start <= day <= end:
                yield day, nm_id, currency, values

    monkeypatch.setattr(buyouts, "rows", rows)
    db = SimpleNamespace(get=lambda *args: SimpleNamespace(format_version=format_version))
    return db


def test_each_day_uses_one_source_and_amounts_stay_separate(monkeypatch):
    old, recent = date(2026, 3, 1), date(2026, 10, 1)
    data = {
        Source.SALES: [
            (recent, "42", "WB", {"sales": "3", "sales_amount": "900", "missing_prices": "0"}),
            # Before the sales window: must be ignored even if present.
            (old, "42", "WB", {"sales": "99", "sales_amount": "1", "missing_prices": "0"}),
        ],
        Source.FINANCE: [
            (
                old,
                "42",
                "RUB",
                {
                    "report_bydate_records": "1",
                    "report_bydate_sales": "2",
                    "report_bydate_sales_amount": "500",
                    "report_bydate_missing_prices": "0",
                },
            ),
            # Report-date-only cell (no sale-date fields): not a buyout.
            (old, "7", "RUB", {"records": "1", "for_pay": "10"}),
            (recent, "42", "RUB", {"report_bydate_records": "1", "report_bydate_sales": "50"}),
        ],
    }
    db = fake(
        monkeypatch,
        sales_known=(date(2026, 7, 25), date(2026, 10, 22)),
        finance_windows=[{"date_from": "2024-01-29", "date_to": "2026-10-19"}],
        data=data,
    )
    result = buyouts.report(db, None, "w", "s", old, old)
    assert result["status"] == "ready" and result["daily"][0]["source"] == "finance_report"
    assert result["totals"] == {"sales": 2, "returns": 0, "net_units": 2}
    assert result["amounts"] == [
        {
            "basis": "retail_price",
            "currency": "RUB",
            "sales_amount": "500.00",
            "returns_amount": "0.00",
            "net_amount": "500.00",
            "missing_prices": 0,
        }
    ]
    both = buyouts.report(db, None, "w", "s", old, recent)
    days = {item["day"]: item for item in both["daily"]}
    assert days[recent.isoformat()]["source"] == "sales_report"
    assert days[recent.isoformat()]["sales"] == 3  # not 3 + 50 from the financial report
    assert both["totals"]["sales"] == 5
    assert {a["basis"] for a in both["amounts"]} == {"buyer_paid", "retail_price"}
    gap = date(2026, 6, 15)
    assert days[gap.isoformat()]["source"] == "finance_report"


def test_unknown_days_and_upgrade_in_progress(monkeypatch):
    day = date(2025, 1, 10)
    db = fake(
        monkeypatch,
        sales_known=(None, None),
        finance_windows=[{"date_from": "2024-01-29", "date_to": "2026-10-19"}],
        data={Source.SALES: [], Source.FINANCE: []},
        format_version=METRIC_FORMAT - 1,
    )
    result = buyouts.report(db, None, "w", "s", day, day)
    assert result["status"] == "preparing" and result["daily"][0]["sales"] is None
    db = fake(
        monkeypatch,
        sales_known=(None, None),
        finance_windows=[],
        data={Source.SALES: [], Source.FINANCE: []},
    )
    nothing = buyouts.report(db, None, "w", "s", day, day)
    assert nothing["status"] == "no_data" and nothing["daily"][0]["source"] is None
    assert nothing["totals"]["sales"] is None  # unknown, not zero
