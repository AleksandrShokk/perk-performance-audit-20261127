"""Regression tests for the 21 October 2026 audit (A08–A11), without a database."""

import threading
import time
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.modules.finance.report import PriceBook, price_for
from app.modules.insights.compute import validated_period
from app.modules.sync.schemas import FINANCE_START, moscow_today
from app.security import crypto
from app.workers.celery_app import HEAVY_QUEUE, celery_app


@pytest.mark.parametrize(
    "date_from,date_to",
    [
        (date(2026, 5, 2), date(2026, 5, 1)),  # reversed
        (date(1, 1, 1), date(1, 1, 2)),  # before available history (was a 500)
        (FINANCE_START, FINANCE_START + timedelta(days=1200)),  # too long / future
        (date(2026, 1, 1), None),  # one bound only
        (None, date(2026, 1, 1)),
    ],
)
def test_a08_every_report_period_is_validated(date_from, date_to):
    with pytest.raises(HTTPException) as error:
        validated_period(date_from, date_to)
    assert error.value.status_code == 422


def test_a08_default_period_is_last_30_closed_days():
    start, end = validated_period(None, None)
    assert end == moscow_today() - timedelta(days=1)
    assert (end - start).days == 29


def test_a09_price_lookup_keeps_rules_and_is_linear():
    raw = {(str(i), "", "RUB"): [(date(2025, 1, 1), Decimal(100))] for i in range(6000)}
    raw.update(
        {(str(i), "b", "RUB"): [(date(2025, 6, 1), Decimal(90))] for i in range(0, 6000, 10)}
    )
    book = PriceBook(raw)
    started = time.perf_counter()
    early = [
        price_for(book, {"nm_id": str(i), "barcode": "", "cost_day": "2025-03-01"}, "RUB")
        for i in range(6000)
    ]
    late = [
        price_for(book, {"nm_id": str(i), "barcode": "", "cost_day": "2026-01-01"}, "RUB")
        for i in range(6000)
    ]
    elapsed = time.perf_counter() - started
    # Before a size price exists the general price applies; afterwards it is unsafe.
    assert all(value == 100 for value in early)
    assert sum(value is None for value in late) == 600
    assert price_for(book, {"nm_id": "0", "barcode": "b", "cost_day": "2026-01-01"}, "RUB") == 90
    assert elapsed < 1.0  # was ~2.5 s for 6 000 lookups with the full scan


def test_a10_heavy_tasks_run_on_their_own_queue():
    routes = celery_app.conf.task_routes
    for name in ("perk.finance.prepare", "perk.insights.compute", "perk.notifications.dispatch"):
        assert routes[name] == {"queue": HEAVY_QUEUE}
    assert "perk.sync.page" not in routes  # WB pages stay on the default sync queue


def test_a11_password_operations_are_bounded(monkeypatch):
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(crypto, "PASSWORD_SLOTS", slots)
    monkeypatch.setattr(crypto, "PASSWORD_WAIT_SECONDS", 0.05)
    slots.acquire()
    try:
        with pytest.raises(HTTPException) as error:
            crypto.verify_password(crypto.DUMMY_PASSWORD_HASH, "x")
        assert error.value.status_code == 503
        assert error.value.headers == {"Retry-After": "5"}
    finally:
        slots.release()
    assert crypto.verify_password(crypto.hash_password("long passphrase 1"), "long passphrase 1")
