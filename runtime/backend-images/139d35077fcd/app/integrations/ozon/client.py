"""Seller API authentication only. Fixed read endpoint, no marketplace mutations."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from fastapi import HTTPException
from pydantic import AwareDatetime, BaseModel, Field, ValidationError

BASE_URL = "https://api-seller.ozon.ru"
MAX_RESPONSE = 262144


def failure(status, code, message, headers=None):
    return HTTPException(status, {"code": code, "message": message}, headers=headers)


class Role(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    methods: list[str] = Field(max_length=2000)


class RolesResponse(BaseModel):
    expires_at: AwareDatetime
    roles: list[Role] = Field(max_length=100)


@dataclass(frozen=True)
class OzonAccess:
    expires_at: datetime
    roles: tuple[str, ...]
    methods: tuple[str, ...]


class OzonClient:
    def __init__(self, transport=None):
        self.transport = transport

    def verify(self, client_id: str, api_key: str) -> OzonAccess:
        try:
            with httpx.Client(
                base_url=BASE_URL,
                timeout=httpx.Timeout(8, connect=3),
                follow_redirects=False,
                trust_env=False,
                transport=self.transport,
            ) as client:
                with client.stream(
                    "POST",
                    "/v1/roles",
                    json={},
                    headers={"Client-Id": client_id, "Api-Key": api_key},
                ) as response:
                    if response.status_code in {400, 401, 403}:
                        raise failure(
                            400, "ozon_key_rejected", "Ozon отклонил Client ID или API Key."
                        )
                    if response.status_code == 429:
                        raw = response.headers.get("Retry-After", "60")
                        delay = min(3600, max(1, int(raw))) if raw.isdecimal() else 60
                        raise failure(
                            429,
                            "ozon_rate_limited",
                            "Достигнут лимит Ozon. Повторите позже.",
                            {"Retry-After": str(delay)},
                        )
                    if response.status_code != 200:
                        raise failure(
                            502, "ozon_unavailable", "Не удалось проверить подключение к Ozon."
                        )
                    raw = bytearray()
                    for chunk in response.iter_bytes():
                        raw.extend(chunk)
                        if len(raw) > MAX_RESPONSE:
                            raise ValueError("oversized")
                    data = RolesResponse.model_validate(json.loads(raw))
            methods = tuple(sorted({method for role in data.roles for method in role.methods}))
            if not methods or any(
                len(method) > 256 or not method.startswith("/") for method in methods
            ):
                raise failure(
                    400, "ozon_permissions_missing", "У ключа Ozon нет доступных методов API."
                )
            if data.expires_at <= datetime.now(UTC):
                raise failure(400, "ozon_key_expired", "Срок действия ключа Ozon истёк.")
            return OzonAccess(
                data.expires_at, tuple(sorted({role.name for role in data.roles})), methods
            )
        except httpx.HTTPError, ValueError, ValidationError, TypeError:
            # Never return provider bodies, headers, keys or exception messages.
            raise failure(
                502, "ozon_unavailable", "Не удалось проверить подключение к Ozon."
            ) from None
