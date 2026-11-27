from datetime import date

from app.modules.finance.history import next_window


def test_current_import_needs_no_history_upgrade():
    assert next_window({date(2026, 1, 1): 100}, set()) == (None, None)


def test_history_window_counts_current_rows_between_old_imports_too():
    first, middle, last = date(2025, 1, 1), date(2025, 1, 2), date(2025, 1, 3)
    assert next_window({first: 100000, middle: 100000, last: 50000}, {first, last}) == (
        first,
        middle,
    )
    assert next_window({first: 100000, middle: 100000, last: 50000}, {last}) == (last, last)


def test_small_stores_can_update_years_in_one_bounded_window():
    first, last = date(2024, 1, 29), date(2026, 7, 31)
    assert next_window({first: 50, last: 100}, {first, last}) == (first, last)


def test_large_day_is_not_skipped_or_replaced_with_an_empty_window():
    first, last = date(2025, 1, 1), date(2025, 1, 2)
    assert next_window({first: 250000, last: 10}, {first, last}) == (first, first)
