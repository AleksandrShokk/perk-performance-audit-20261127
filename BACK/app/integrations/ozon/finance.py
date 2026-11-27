"""Current accrual API, complete day pagination, no legacy transaction endpoints."""

from datetime import timedelta

from app.integrations.ozon.transport import OzonImportError, SellerReader

BY_DAY = "/v1/finance/accrual/by-day"
TYPES = "/v1/finance/accrual/types"


class FinanceClient(SellerReader):
    allowed_methods = frozenset({BY_DAY, TYPES})

    def types(self):
        rows = self.read(TYPES, {}).get("accrual_types")
        if (
            not isinstance(rows, list)
            or any(
                not isinstance(row.get("id"), int) or not isinstance(row.get("name"), str)
                for row in rows
            )
            or len({row["id"] for row in rows}) != len(rows)
        ):
            raise OzonImportError("ozon_invalid_response")
        return {
            row["id"]: {"name": row["name"], "title": row.get("description") or row["name"]}
            for row in rows
        }

    def day(self, day):
        cursor, seen, count = "", set(), 0
        while True:
            data = self.read(BY_DAY, {"date": day.isoformat(), "last_id": cursor})
            rows, next_id = data.get("accruals"), data.get("last_id", "")
            if not isinstance(rows, list) or not isinstance(next_id, str):
                raise OzonImportError("ozon_invalid_response")
            count += len(rows)
            if count > 200000:
                raise OzonImportError("ozon_import_limit")
            yield from rows
            if not next_id:
                return
            if not rows or next_id == cursor or next_id in seen:
                raise OzonImportError("ozon_cursor_repeated")
            seen.add(next_id)
            cursor = next_id

    def days(self, start, end, normalize, progress=lambda count: None):
        days, count = {}, 0
        try:
            with self:
                types = self.types()
                day = end
                while day >= start:
                    result = normalize(list(self.day(day)), day, types)
                    days[day] = result
                    count += result["records"]
                    progress(count)
                    day -= timedelta(days=1)
            return days, count
        except KeyError, TypeError, ValueError, ArithmeticError:
            raise OzonImportError("ozon_invalid_response") from None
