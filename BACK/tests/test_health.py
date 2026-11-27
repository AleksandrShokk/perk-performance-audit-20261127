from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.exc import OperationalError

from app.main import create_app


@pytest.fixture
def client(isolated_settings):
    with patch("app.main.build_engine"), patch("app.main.Redis.from_url"):
        application = create_app(isolated_settings)
        with TestClient(application) as test_client:
            yield test_client


def test_liveness_does_not_require_database_or_redis(client):
    response = client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "perk-api"}
    client.app.state.db_engine.connect.assert_not_called()
    client.app.state.redis.ping.assert_not_called()


@pytest.mark.parametrize(
    "database_ok,redis_ok", [(True, True), (False, True), (True, False), (False, False)]
)
def test_readiness_reports_dependency_failure_without_leaking_secrets(
    client, database_ok, redis_ok
):
    if not database_ok:
        client.app.state.db_engine.connect.side_effect = OperationalError(
            "SELECT 1", {}, Exception("postgres password=do-not-expose")
        )
    if not redis_ok:
        client.app.state.redis.ping.side_effect = RedisConnectionError("redis://secret@host")
    response = client.get("/api/v1/health/ready")
    assert response.status_code == (200 if database_ok and redis_ok else 503)
    assert response.json()["dependencies"] == {
        "database": "ok" if database_ok else "unavailable",
        "redis": "ok" if redis_ok else "unavailable",
    }
    assert "secret" not in response.text
    assert "do-not-expose" not in response.text


def test_openapi_contract_has_stable_operation_ids_and_unavailable_response(client):
    schema = client.get("/openapi.json").json()
    assert schema["paths"]["/api/v1/health/live"]["get"]["operationId"] == "healthLive"
    ready = schema["paths"]["/api/v1/health/ready"]["get"]
    assert ready["operationId"] == "healthReady"
    assert "503" in ready["responses"]


@pytest.mark.parametrize(
    "origin,allowed", [("http://localhost:3000", True), ("https://other.test", False)]
)
def test_cors_only_allows_configured_frontend_origins(client, origin, allowed):
    response = client.options(
        "/api/v1/health/live",
        headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
    )
    assert (response.headers.get("access-control-allow-origin") == origin) is allowed
