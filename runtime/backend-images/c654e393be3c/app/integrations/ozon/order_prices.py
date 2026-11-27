"""Buyer prices omitted by FBO list: join the official order export by posting and SKU."""

import csv
import io
from collections import defaultdict
from decimal import Decimal
from urllib.parse import urlsplit

import httpx

from app.integrations.ozon.transport import OzonImportError, SellerReader

CREATE = "/v1/report/postings/create"
INFO = "/v1/report/info"
MAX_BYTES = 32 * 1024 * 1024
HEADERS = (
    "Номер отправления",
    "SKU",
    "Количество",
    "Оплачено покупателем",
    "Код валюты покупателя",
)


def parse(raw, required=None):
    # Ozon's posting export is UTF-8 CSV. Refuse a changed format rather than read a wrong price.
    text = raw.decode("utf-8-sig")
    dialect = csv.Sniffer().sniff(text[:8192], delimiters=";,\t")
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames or not set(HEADERS) <= set(reader.fieldnames):
        raise ValueError("price_report_columns")
    candidates = defaultdict(list)
    for index, row in enumerate(reader):
        if index >= 200000:
            raise ValueError("price_report_limit")
        number, sku = row[HEADERS[0]], row[HEADERS[1]]
        if required is not None and (number, sku) not in required:
            continue
        quantity = int(row[HEADERS[2]])
        amount, currency = row[HEADERS[3]], row[HEADERS[4]]
        price = (
            None
            if amount in (None, "", "-")
            else Decimal(amount.replace(" ", "").replace("\xa0", "").replace(",", "."))
        )
        if not number or not sku.isdecimal() or quantity <= 0:
            raise ValueError("price_report_identity")
        if price is not None and not currency:
            # An absent currency cannot establish a buyer price, even for zero.
            price, currency = None, None
        elif price is not None and (len(currency) != 3 or not currency.isupper()):
            raise ValueError("price_report_currency")
        if price is not None and (not price.is_finite() or price < 0 or price.adjusted() > 30):
            raise ValueError("price_report_amount")
        candidates[(number, sku)].append((quantity, price, currency))
    return candidates


def apply(postings, candidates):
    for posting in postings:
        for item in posting["items"]:
            rows = candidates.get((posting["number"], item["sku"]), [])
            if sum(row[0] for row in rows) != item["quantity"]:
                raise OzonImportError("ozon_price_report_incomplete", 60)
            quotes = {(price, currency) for _, price, currency in rows}
            if len(quotes) != 1:
                raise OzonImportError("ozon_price_report_conflict", 3600)
            price, currency = next(iter(quotes))
            item["price"] = str(price) if price is not None else None
            item["currency"] = currency
            if currency is None:
                item["price_status"] = "currency_missing"


class OrderPrices(SellerReader):
    allowed_methods = frozenset({CREATE, INFO})

    def __init__(self, *args, checkpoint=None, pause, **kwargs):
        super().__init__(*args, **kwargs)
        self.checkpoint, self.pause = checkpoint, pause

    def download(self, url):
        address = urlsplit(url)
        host = address.hostname or ""
        if (
            address.scheme != "https"
            or address.username
            or address.password
            or address.port not in (None, 443)
            or not (host == "ozone.ru" or host.endswith(".ozone.ru"))
        ):
            raise OzonImportError("ozon_invalid_report_url")
        # Signed report URLs never receive API credentials, cookies, proxies, or redirects.
        with httpx.Client(
            transport=self.transport,
            timeout=30,
            trust_env=False,
            follow_redirects=False,
        ) as client:
            with client.stream("GET", url) as response:
                if response.status_code != 200:
                    raise OzonImportError("ozon_report_unavailable", 60)
                raw = bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw) > MAX_BYTES:
                        raise OzonImportError("ozon_response_too_large")
        return bytes(raw)

    def enrich(self, postings, start, end, period):
        from app.integrations.ozon.operations import boundaries

        for channel in ("fbo", "fbs"):
            selected = [row for row in postings if row["channel"] == channel]
            selected = [
                {
                    **row,
                    "items": [
                        item
                        for item in row["items"]
                        if item["price"] is None and not item.get("price_status")
                    ],
                }
                for row in selected
            ]
            selected = [row for row in selected if row["items"]]
            if not selected:
                continue
            state = (
                self.checkpoint.load([period, channel])
                if self.checkpoint
                else {"completed": [], "rows": []}
            )
            code = state.get("code")
            if not code:
                dates = boundaries(start, end)
                data = self.read(
                    CREATE,
                    {
                        "language": "RU",
                        "filter": {
                            "delivery_schema": [channel],
                            "processed_at_from": dates["since"],
                            "processed_at_to": dates["to"],
                        },
                        "with": {"customer_data": False},
                    },
                )
                code = data["result"]["code"]
                if not isinstance(code, str) or not code:
                    raise ValueError("report_code")
                state["code"] = code
                if self.checkpoint:
                    self.checkpoint.save(state)
            for attempt in range(16):
                data = self.read(INFO, {"code": code})["result"]
                if data["status"] == "success":
                    required = {
                        (row["number"], item["sku"]) for row in selected for item in row["items"]
                    }
                    try:
                        apply(selected, parse(self.download(data["file"]), required))
                    except (
                        ValueError,
                        KeyError,
                        TypeError,
                        ArithmeticError,
                        csv.Error,
                    ):
                        if self.checkpoint:
                            self.checkpoint.clear()
                        raise OzonImportError("ozon_price_report_invalid", 3600) from None
                    if self.checkpoint:
                        self.checkpoint.clear()
                    break
                if data["status"] == "failed":
                    if self.checkpoint:
                        self.checkpoint.clear()
                    raise OzonImportError("ozon_report_failed", 60)
                if data["status"] not in {"waiting", "processing"}:
                    raise ValueError("report_status")
                if attempt == 15:
                    raise OzonImportError("ozon_report_preparing", 30)
                self.pause(2)
