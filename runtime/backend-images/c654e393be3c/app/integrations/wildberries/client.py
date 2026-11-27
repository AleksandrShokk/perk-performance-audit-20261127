import base64
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import httpx
from fastapi import HTTPException

# Official fixed destination. Never accept a URL, proxy, redirect or host from the caller.
SELLER_INFO_URL = "https://common-api.wildberries.ru/api/v1/seller-info"
SCOPES = {
    1: "content",
    2: "analytics",
    3: "prices",
    4: "marketplace",
    5: "statistics",
    6: "promotion",
    10: "supplies",
    12: "documents",
    13: "finance",
}
READ_ONLY = 1 << 30
ALLOWED_MASK = READ_ONLY | sum(1 << bit for bit in SCOPES)


@dataclass(frozen=True)
class TokenMetadata:
    seller_id: str
    scopes: list[str]
    expires_at: datetime
    token_type: int


def inspect_token(
    token: str,
    *,
    production: bool = False,
    service_id: str | None = None,
    allow_personal: bool = False,
) -> TokenMetadata:
    """Policy precheck only. Decoding is NOT signature verification; WB must accept this token."""
    try:
        if len(token) > 8192 or any(char.isspace() for char in token):
            raise ValueError
        header, body, signature = token.split(".")
        if not signature:
            raise ValueError
        headers = json.loads(base64.urlsafe_b64decode(header + "=" * (-len(header) % 4)))
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        if headers.get("alg") not in {"HS256", "RS256", "ES256"}:
            raise ValueError
        mask, expiry = payload["s"], payload["exp"]
        if type(mask) is not int or type(expiry) is not int or mask < 0 or expiry <= time.time():
            raise ValueError
        seller_id = str(UUID(payload["sid"]))
        expires_at = datetime.fromtimestamp(expiry, UTC)
        if payload.get("t") is not False or payload.get("acc") not in {1, 3, 4}:
            raise ValueError
    except ValueError, KeyError, TypeError, OverflowError, AttributeError:
        raise HTTPException(400, "Токен WB недействителен или срок его действия истёк.") from None
    if not mask & READ_ONLY:
        raise HTTPException(400, "Нужен токен WB только для чтения.")
    if mask & ~ALLOWED_MASK:
        raise HTTPException(
            400,
            "Уберите из токена WB доступ к пользователям и коммуникациям.",
        )
    scopes = [name for bit, name in SCOPES.items() if mask & (1 << bit)]
    if not scopes:
        raise HTTPException(400, "У токена WB нет нужных прав для аналитики.")
    if production:
        own_service = (
            bool(service_id) and payload["acc"] == 4 and payload.get("for") == f"asid:{service_id}"
        )
        beta_personal = allow_personal and payload["acc"] == 3 and payload.get("for") == "self"
        if not own_service and not beta_personal:
            message = (
                "Для тестирования нужен персональный токен WB только для чтения."
                if allow_personal
                else "Для подключения WB нужен сервисный токен, выданный для PERK."
            )
            raise HTTPException(400, message)
    return TokenMetadata(seller_id, scopes, expires_at, payload["acc"])


class WildberriesClient:
    def __init__(self, transport=None):
        self.transport = transport

    def verify(self, token: str, expected: TokenMetadata) -> TokenMetadata:
        try:
            with httpx.Client(
                timeout=httpx.Timeout(10, connect=3),
                follow_redirects=False,
                trust_env=False,
                transport=self.transport,
            ) as client:
                with client.stream(
                    "GET", SELLER_INFO_URL, headers={"Authorization": token}
                ) as response:
                    if response.status_code in {401, 403}:
                        raise HTTPException(
                            400, "Wildberries отклонил токен. Проверьте его или создайте новый."
                        )
                    if response.status_code == 429:
                        raise HTTPException(
                            429,
                            "Достигнут лимит запросов Wildberries. Попробуйте позже.",
                            headers={"Retry-After": "60"},
                        )
                    if response.status_code != 200:
                        raise HTTPException(
                            502, "Не удалось проверить токен Wildberries. Попробуйте позже."
                        )
                    raw = bytearray()
                    for chunk in response.iter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 65536:
                            raise HTTPException(
                                502, "Wildberries вернул некорректный ответ. Попробуйте позже."
                            )
                    result = json.loads(raw)
            if str(UUID(result["sid"])) != expected.seller_id:
                raise HTTPException(400, "Токен WB относится к другому продавцу.")
            return expected
        except httpx.HTTPError, ValueError, KeyError, TypeError:
            raise HTTPException(
                502, "Не удалось проверить токен Wildberries. Попробуйте позже."
            ) from None
