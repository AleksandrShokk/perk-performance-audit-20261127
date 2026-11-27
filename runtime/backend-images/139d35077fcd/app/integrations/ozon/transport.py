"""Bounded, read-only Seller API transport shared by marketplace readers."""

import json
from contextlib import nullcontext
from decimal import Decimal

import httpx

from app.integrations.ozon.client import BASE_URL


class OzonImportError(Exception):
    def __init__(self, code, retry_after=300):
        self.code, self.retry_after = code, retry_after
        super().__init__(code)


class SellerReader:
    allowed_methods = frozenset()

    def __init__(self, client_id, api_key, *, transport=None, wait=lambda: None):
        self.headers = {"Client-Id": client_id, "Api-Key": api_key}
        self.transport, self.wait, self.session = transport, wait, None

    def connection(self):
        return httpx.Client(
            base_url=BASE_URL,
            headers=self.headers,
            transport=self.transport,
            timeout=httpx.Timeout(20, connect=5),
            trust_env=False,
            follow_redirects=False,
        )

    def __enter__(self):
        self.session = self.connection()
        return self

    def __exit__(self, *args):
        self.session.close()
        self.session = None

    def read(self, path, body):
        if path not in self.allowed_methods:
            raise ValueError("Unsupported read method")
        self.wait()
        try:
            with nullcontext(self.session) if self.session else self.connection() as client:
                with client.stream("POST", path, json=body) as response:
                    if response.status_code in {401, 403}:
                        raise OzonImportError("ozon_access_denied", 3600)
                    if response.status_code == 429:
                        raw = response.headers.get("Retry-After", "60")
                        raise OzonImportError(
                            "ozon_rate_limited",
                            min(3600, max(60, int(raw))) if raw.isdecimal() else 60,
                        )
                    if response.status_code != 200:
                        raise OzonImportError("ozon_unavailable")
                    raw = bytearray()
                    for chunk in response.iter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 32 * 1024 * 1024:
                            raise OzonImportError("ozon_response_too_large")
                    data = json.loads(raw, parse_float=Decimal)
                    if not isinstance(data, dict):
                        raise ValueError("response_shape")
                    return data
        except httpx.HTTPError, ValueError, TypeError:
            # Provider bodies, PII, headers and credentials never enter logs/errors.
            raise OzonImportError("ozon_invalid_response") from None
