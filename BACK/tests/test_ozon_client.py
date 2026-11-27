import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.integrations.ozon.client import MAX_RESPONSE, OzonClient
from app.modules.accounts.schemas import ConnectOzonInput

KEY = "synthetic-never-a-real-credential"


def payload():
    return {
        "expires_at": (datetime.now(UTC) + timedelta(days=60)).isoformat(),
        "roles": [{"name": "ReadOnly", "methods": ["/v3/product/list", "/v1/roles"]}],
    }


def test_fixed_read_endpoint_checks_headers_and_permissions():
    requests = []

    def respond(request):
        requests.append(request)
        assert (
            request.method == "POST" and str(request.url) == "https://api-seller.ozon.ru/v1/roles"
        )
        assert json.loads(request.content) == {}
        assert request.headers["Client-Id"] == "12345" and request.headers["Api-Key"] == KEY
        return httpx.Response(200, json=payload())

    data = OzonClient(httpx.MockTransport(respond)).verify("12345", KEY)
    assert len(requests) == 1 and data.roles == ("ReadOnly",)
    assert set(data.methods) == {"/v3/product/list", "/v1/roles"}
    assert data.expires_at.tzinfo is not None


@pytest.mark.parametrize(
    "status,expected", [(400, 400), (401, 400), (403, 400), (500, 502), (302, 502)]
)
def test_provider_errors_are_redacted_and_redirects_are_never_followed(status, expected):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(status, text=KEY, headers={"Location": "https://other.test"})

    with pytest.raises(HTTPException) as caught:
        OzonClient(httpx.MockTransport(respond)).verify("12345", KEY)
    assert caught.value.status_code == expected and KEY not in str(caught.value.detail)
    assert len(calls) == 1


@pytest.mark.parametrize("header,expected", [("36000", "3600"), ("oops", "60"), ("12", "12")])
def test_retry_after_is_bounded(header, expected):
    with pytest.raises(HTTPException) as caught:
        OzonClient(
            httpx.MockTransport(lambda r: httpx.Response(429, headers={"Retry-After": header}))
        ).verify("12345", KEY)
    assert caught.value.status_code == 429 and caught.value.headers == {"Retry-After": expected}


@pytest.mark.parametrize(
    "value,expected",
    [
        ({}, 502),
        ({"roles": []}, 502),
        ({**payload(), "roles": []}, 400),
        ({**payload(), "expires_at": "2020-01-01T00:00:00Z"}, 400),
        ({**payload(), "expires_at": "2026-11-01"}, 502),
    ],
)
def test_unknown_expiry_and_missing_access_never_create_a_valid_connection(value, expected):
    with pytest.raises(HTTPException) as caught:
        OzonClient(httpx.MockTransport(lambda r: httpx.Response(200, json=value))).verify(
            "12345", KEY
        )
    assert caught.value.status_code == expected


def test_oversized_body_is_rejected():
    with pytest.raises(HTTPException) as caught:
        OzonClient(
            httpx.MockTransport(lambda r: httpx.Response(200, content=b"x" * (MAX_RESPONSE + 1)))
        ).verify("12345", KEY)
    assert caught.value.status_code == 502


@pytest.mark.parametrize(
    "change",
    [
        {"client_id": "1\r\nInjected:yes"},
        {"client_id": "-1"},
        {"api_key": KEY + "\nInjected"},
        {"name": "   "},
    ],
)
def test_invalid_identifiers_and_header_injection_are_rejected(change):
    with pytest.raises(ValidationError):
        ConnectOzonInput.model_validate(
            {"client_id": "12345", "api_key": KEY, "name": "Shop", **change}
        )
