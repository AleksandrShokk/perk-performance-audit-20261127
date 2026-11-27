from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from cryptography.exceptions import InvalidTag

from app.integrations.wildberries.data import Source, WBDataClient
from app.modules.auth.dependencies import now
from app.modules.sync.analytics import abc_rows, cache_address, contribution, metric_context
from app.modules.sync.planner import next_run
from app.modules.sync.schemas import FINANCE_START, ConfigureSchedule, history_limits, moscow_today


def plan(source, **changes):
    return SimpleNamespace(
        **{
            "source": source,
            "recent_days": 30,
            "recent_completed": False,
            "next_refresh_at": now() + timedelta(hours=6),
            "sales_cursor": None,
            "history_from": history_limits()[source]["date_from"],
            "backfill_to": moscow_today() - timedelta(days=31),
            "reconcile_at": now() + timedelta(days=7),
            "history_turn": False,
            "backfill_chunk_days": 3650,
            **changes,
        }
    )


def test_recent_month_first_then_monthly_history_and_refresh_fairness():
    # Legacy plans stored a ten-year chunk: history is still published month by month.
    value = plan(Source.FINANCE)
    mode, start, end, _ = next_run(value)
    assert mode == "recent" and (end - start).days == 29
    value.recent_completed = True
    mode, start, end, _ = next_run(value)
    assert mode == "backfill" and end == value.backfill_to and (end - start).days == 30
    assert start > FINANCE_START
    value.backfill_chunk_days = 5  # sync_size_limit may still shrink a chunk.
    mode, start, end, _ = next_run(value)
    assert (end - start).days == 4
    value.backfill_chunk_days = 3650
    value.next_refresh_at = now() - timedelta(hours=12)
    assert next_run(value)[0] == "incremental"
    value.history_turn = True
    assert next_run(value)[0] == "backfill"  # Long provider pauses cannot starve history.


def test_sales_change_overlap_clamped_to_provider_retention():
    value = plan(
        Source.SALES,
        recent_completed=True,
        next_refresh_at=now(),
        sales_cursor=(moscow_today() - timedelta(days=1)).isoformat(),
    )
    mode, start, end, cursor = next_run(value)
    assert mode == "incremental" and start == history_limits()[Source.SALES]["date_from"]
    assert end == moscow_today()
    assert cursor["last_change"][:10] == (moscow_today() - timedelta(days=4)).isoformat()
    value.sales_cursor = FINANCE_START.isoformat()
    assert next_run(value)[3]["last_change"][:10] == start.isoformat()


def test_finance_weekly_reconciliation_does_not_invent_a_change_cursor():
    value = plan(Source.FINANCE, recent_completed=True, next_refresh_at=now(), reconcile_at=now())
    mode, start, end, cursor = next_run(value)
    assert mode == "reconcile" and (end - start).days == 89 and cursor == {}


def test_finance_oversize_reduces_page_without_advancing_cursor_or_extra_call(monkeypatch):
    from app.integrations.wildberries import data

    calls = []
    monkeypatch.setattr(data, "MAX_BYTES", 100)

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=[{"rrdId": 12, "padding": "x" * 200}])

    result = WBDataClient(httpx.MockTransport(handler)).page(
        Source.FINANCE, "synthetic", {"rrdId": 10}, FINANCE_START, moscow_today()
    )
    assert len(calls) == 1 and not result.complete and result.rows == []
    assert result.cursor == {"rrdId": 10, "page_size": 50000}


def test_finance_small_full_page_can_grow_next_request():
    client = WBDataClient(
        httpx.MockTransport(
            lambda request: httpx.Response(200, json=[{"rrdId": i} for i in range(1, 1001)])
        )
    )
    result = client.page(
        Source.FINANCE, "synthetic", {"page_size": 1000}, FINANCE_START, moscow_today()
    )
    assert result.cursor == {"rrdId": 1000, "page_size": 2000}


def test_returns_exact_money_and_abc_boundaries():
    _, values = contribution(
        Source.FINANCE,
        {
            "report_date": "2026-10-01",
            "nm_id": "1",
            "currency": "RUB",
            "quantity": 1,
            "document_type": "Возврат",
            "retail_amount": "12.34",
            "for_pay": "10.01",
            "acquiring_fee": None,
        },
    )
    assert values["for_pay"] == Decimal("-10.01") and values["missing_acquiring_fee"] == 1
    products = {
        str(i): {"sales": Decimal(q), "returns": Decimal(0)} for i, q in enumerate([80, 15, 5, -1])
    }
    rows, count = abc_rows(products, 100)
    assert count == 3 and [row["class"] for row in rows] == ["A", "B", "C"]
    assert rows[-1]["cumulative_percent"] == "100.00"


def test_metric_and_cache_ciphertext_bound_to_tenant_dataset_and_period(vault):
    ws, store = uuid4(), uuid4()
    aad = metric_context(ws, store, "sales", "published", "2026-10-01", "1", "WB")
    encrypted = vault.seal('{"sales":"1"}', aad)
    with pytest.raises(InvalidTag):
        vault.open(
            encrypted, metric_context(ws, store, "sales", "other-run", "2026-10-01", "1", "WB")
        )
    key, context = cache_address(vault, ws, store, "v1", "2026-10-01", "2026-10-02", 100)
    foreign_key, foreign = cache_address(
        vault, uuid4(), store, "v1", "2026-10-01", "2026-10-02", 100
    )
    assert key != foreign_key
    with pytest.raises(InvalidTag):
        vault.open(vault.seal("synthetic-dashboard", context), foreign)


def test_schedule_rejects_unknown_options_and_duplicate_sources():
    with pytest.raises(ValueError):
        ConfigureSchedule(sources=["sales", "sales"])
    with pytest.raises(ValueError):
        ConfigureSchedule(recent_days=365)
    with pytest.raises(ValueError):
        ConfigureSchedule(skip_rate_limits=True)
