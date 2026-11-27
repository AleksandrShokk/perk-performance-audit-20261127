import logging
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.core import timing
from app.core.timing import TimingMiddleware


def build(vault, slow_ms=1000):
    application = FastAPI()
    application.add_middleware(TimingMiddleware, slow_ms=slow_ms)

    @application.get("/api/v1/workspaces/{workspace_id}/report")
    def report(workspace_id: str):  # Sync handler: runs in the thread pool like the real API.
        sealed = vault.seal("secret-report", "context")
        assert vault.open(sealed, "context") == "secret-report"
        timing.add("db", 0.002)
        return {"ok": True}

    @application.post("/api/v1/auth/login")
    def login():
        timing.add("db", 0.001)
        return {"ok": True}

    @application.get("/api/v1/health/live")
    def live():
        return {"ok": True}

    @application.get("/api/v1/slow")
    def slow():
        time.sleep(0.06)
        return {"ok": True}

    return application


def parse(value):
    metrics = {}
    for part in value.split(", "):
        name, *fields = part.split(";")
        metrics[name] = dict(field.split("=", 1) for field in fields)
    return metrics


def test_api_responses_split_time_into_database_crypto_and_application(vault):
    client = TestClient(build(vault))
    response = client.get("/api/v1/workspaces/abc/report")
    assert response.status_code == 200
    metrics = parse(response.headers["server-timing"])
    assert set(metrics) == {"db", "crypto", "app", "total"}
    assert metrics["db"]["desc"] == '"1 SQL"'
    assert metrics["crypto"]["desc"] == '"2 ops"'
    assert float(metrics["db"]["dur"]) == 2.0
    assert float(metrics["total"]["dur"]) > 0


def test_auth_and_health_responses_carry_no_timing_details(vault):
    client = TestClient(build(vault))
    assert "server-timing" not in client.post("/api/v1/auth/login").headers
    assert "server-timing" not in client.get("/api/v1/health/live").headers


def test_slow_requests_are_logged_by_route_template_only(vault, caplog):
    client = TestClient(build(vault, slow_ms=50))
    with caplog.at_level(logging.WARNING, logger="perk.timing"):
        client.get("/api/v1/slow")
        client.get("/api/v1/workspaces/secret-workspace-id/report")
    lines = [record.getMessage() for record in caplog.records]
    assert any("route=/api/v1/slow" in line and "status=200" in line for line in lines)
    assert not any("secret-workspace-id" in line for line in lines)


def test_measurements_outside_a_request_are_ignored(vault):
    sealed = vault.seal("value", "context")
    assert vault.open(sealed, "context") == "value"
    assert timing.current.get() is None


def test_engine_statements_are_counted_inside_a_request():
    engine = create_engine("sqlite://")
    timing.instrument_engine(engine)
    values = {}
    token = timing.current.set(values)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            connection.execute(text("SELECT 2"))
    finally:
        timing.current.reset(token)
    assert values["db_count"] == 2
    assert values["db"] > 0
