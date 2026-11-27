from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.core.errors import body, failure_location, request_id
from app.main import create_app
from app.modules.auth.schemas import LoginInput


@pytest.fixture
def client(isolated_settings):
    with patch("app.main.build_engine"), patch("app.main.Redis.from_url"):
        application = create_app(isolated_settings)

        @application.get("/api/v1/health/boom-coded")
        def coded():
            raise HTTPException(403, {"code": "step_up_required", "message": "Confirm"})

        @application.get("/api/v1/health/boom-plain")
        def plain():
            raise HTTPException(404, "Store not found")

        @application.post("/api/v1/health/echo")
        def echo(data: LoginInput):
            return {}

        with TestClient(application) as test_client:
            test_client.app.state.redis.eval.return_value = 1  # under every rate limit
            yield test_client


def test_errors_keep_detail_and_add_code_message_and_request_id(client):
    coded = client.get("/api/v1/health/boom-coded", headers={"X-Request-ID": "trace-12345678"})
    assert coded.status_code == 403
    assert coded.json() == {
        "detail": {"code": "step_up_required", "message": "Confirm"},
        "code": "step_up_required",
        "message": "Confirm",
        "request_id": "trace-12345678",
    }
    assert coded.headers["x-request-id"] == "trace-12345678"
    plain = client.get("/api/v1/health/boom-plain").json()
    assert plain["code"] == "not_found" and plain["message"] == "Store not found"
    assert len(plain["request_id"]) == 32


def test_validation_errors_hide_input_and_have_a_code(client):
    response = client.post("/api/v1/health/echo", json={"email": "bad", "password": "secret-value"})
    assert response.status_code == 422
    data = response.json()
    assert data["code"] == "validation_error"
    assert "secret-value" not in response.text


def test_unsafe_request_id_is_replaced(client):
    response = client.get("/api/v1/health/live", headers={"X-Request-ID": "bad id\r\nx"})
    assert response.headers["x-request-id"] != "bad id\r\nx"
    assert len(response.headers["x-request-id"]) == 32


def test_unknown_route_uses_the_same_shape(client):
    data = client.get("/api/v1/nope").json()
    assert data["code"] == "not_found" and "request_id" in data


def test_failure_location_has_no_message():
    try:
        raise ValueError("password=hunter2")
    except ValueError as exc:
        location = failure_location(exc)
    assert "hunter2" not in location and ":" in location


def test_body_outside_a_request():
    assert body(429, "Too many")["request_id"] == request_id.get()


def test_request_context_follows_queued_tasks_and_is_reset():
    from types import SimpleNamespace

    from app.core.errors import task_id
    from app.workers.celery_app import bind_task_id, propagate_request_id, unbind_task_id

    token = request_id.set("trace-12345678")
    try:
        headers = {}
        propagate_request_id(headers=headers)
        assert headers == {"perk_request_id": "trace-12345678"}
    finally:
        request_id.reset(token)
    task = SimpleNamespace(request=SimpleNamespace(headers=headers))
    bind_task_id(task_id="job-1", task=task)
    try:
        assert request_id.get() == "trace-12345678"
        assert task_id.get() == "job-1"
        downstream = {}
        propagate_request_id(headers=downstream)
        assert downstream == headers
    finally:
        unbind_task_id(task_id="job-1")
    assert request_id.get() == "-" and task_id.get() == "-"
