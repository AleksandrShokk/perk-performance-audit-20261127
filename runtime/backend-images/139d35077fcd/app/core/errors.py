"""One error shape for every response and a request id that follows logs and tasks.

Every error body keeps `detail` (backward compatible) and adds:
  code       — stable machine-readable reason, e.g. "step_up_required", "not_found";
  message    — human-readable text;
  request_id — the same value as the X-Request-ID header and in server logs.
"""

import logging
import re
import traceback
from contextvars import ContextVar
from uuid import uuid4

from pydantic import BaseModel, JsonValue

from app.core.error_messages import public_message


class ErrorResponse(BaseModel):
    detail: JsonValue
    code: str
    message: str
    request_id: str


request_id: ContextVar[str] = ContextVar("request_id", default="-")
task_id: ContextVar[str] = ContextVar("task_id", default="-")
SAFE_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")
STATUS_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    410: "gone",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    502: "upstream_unavailable",
    503: "unavailable",
}


class RequestIdFilter(logging.Filter):
    def filter(self, record):
        record.request_id = request_id.get()
        record.task_id = task_id.get()
        return True


def body(status, detail):
    if isinstance(detail, dict) and "code" in detail:
        code, message = detail["code"], detail.get("message") or ""
    else:
        code = STATUS_CODES.get(status, "error")
        message = detail if isinstance(detail, str) else ""
    message = public_message(message, status)
    if isinstance(detail, str):
        detail = message
    elif isinstance(detail, dict):
        detail = {**detail, "message": message}
    return {"detail": detail, "code": code, "message": message, "request_id": request_id.get()}


def failure_location(exc):
    """Innermost application frame as file:line — no message, locals or SQL parameters."""
    frames = [
        frame
        for frame in traceback.extract_tb(exc.__traceback__)
        if "/app/" in frame.filename.replace("\\", "/")
        and "/.venv/" not in frame.filename.replace("\\", "/")
        and "/site-packages/" not in frame.filename.replace("\\", "/")
    ] or traceback.extract_tb(exc.__traceback__)
    if not frames:
        return "-"
    frame = frames[-1]
    path = frame.filename.replace("\\", "/")
    return f"{path[path.rfind('/app/') + 1 :] if '/app/' in path else path}:{frame.lineno}"


class RequestIdMiddleware:
    """Outermost: assigns the id before any other middleware can answer or fail."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        supplied = ""
        for name, value in scope.get("headers", []):
            if name == b"x-request-id":
                supplied = value.decode("latin-1")
                break
        value = supplied if SAFE_ID.fullmatch(supplied) else uuid4().hex
        token = request_id.set(value)

        async def with_id(message):
            if message["type"] == "http.response.start":
                message["headers"] = [
                    *message.get("headers", []),
                    (b"x-request-id", value.encode()),
                ]
            await send(message)

        try:
            await self.app(scope, receive, with_id)
        finally:
            request_id.reset(token)
