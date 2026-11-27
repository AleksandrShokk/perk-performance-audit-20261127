import logging
from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/health", tags=["Health"])


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str = "perk-api"


class DependencyStatus(BaseModel):
    database: Literal["ok", "unavailable"]
    redis: Literal["ok", "unavailable"]


class ReadinessResponse(BaseModel):
    status: Literal["ok", "unavailable"]
    dependencies: DependencyStatus


@router.get("/live", operation_id="healthLive")
def live() -> HealthResponse:
    """Process is running. Does not depend on PostgreSQL or Redis."""
    return HealthResponse()


@router.get(
    "/ready",
    operation_id="healthReady",
    responses={503: {"model": ReadinessResponse, "description": "A dependency is unavailable"}},
)
def ready(request: Request, response: Response) -> ReadinessResponse:
    """Check database and broker connections; does not check workers or migration versions."""
    dependencies = DependencyStatus(database="ok", redis="ok")
    try:
        with request.app.state.db_engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        dependencies.database = "unavailable"
        logger.warning("Database readiness check failed")

    try:
        request.app.state.redis.ping()
    except RedisError:
        dependencies.redis = "unavailable"
        logger.warning("Redis readiness check failed")

    available = dependencies.database == "ok" and dependencies.redis == "ok"
    if not available:
        response.status_code = 503
    return ReadinessResponse(status="ok" if available else "unavailable", dependencies=dependencies)
