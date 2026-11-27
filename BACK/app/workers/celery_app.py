import logging

from celery import Celery
from celery.signals import (
    after_setup_logger,
    after_setup_task_logger,
    before_task_publish,
    task_postrun,
    task_prerun,
)

from app.core.config import get_settings
from app.core.errors import RequestIdFilter, request_id
from app.core.errors import task_id as current_task_id
from app.core.logging import FORMAT

settings = get_settings()
# Long recalculations never occupy the workers that fetch WB pages on schedule.
HEAVY_QUEUE = "perk-heavy"
HEAVY_TASKS = (
    "perk.finance.prepare",
    "perk.insights.compute",
    "perk.insights.warm",
    "perk.analytics.warm",
    "perk.analytics.warm_store",
    "perk.notifications.dispatch",
    "perk.maintenance.cleanup",
)
celery_app = Celery(
    "perk",
    broker=settings.redis_broker_url,
    backend=settings.redis_result_url,
    include=[
        "app.workers.tasks",
        "app.modules.catalog.tasks",
        "app.modules.catalog.ozon_jobs",
        "app.modules.insights.ozon_jobs",
        "app.modules.supplies.destinations.jobs",
    ],
)
celery_app.conf.update(
    task_default_queue="perk",
    task_routes={
        **{name: {"queue": HEAVY_QUEUE} for name in HEAVY_TASKS},
        "perk.ozon.catalog.import": {"queue": "perk-ozon"},
        "perk.ozon.analytics.import": {"queue": "perk-ozon"},
    },
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    broker_connection_timeout=3,
    broker_transport_options={"socket_connect_timeout": 3, "socket_timeout": 3},
    redis_socket_connect_timeout=3,
    redis_socket_timeout=3,
    task_soft_time_limit=1740,
    task_time_limit=1800,
    result_expires=3600,
    beat_schedule={
        "dispatch-supply-destinations": {
            "task": "perk.supply.destinations.dispatch",
            "schedule": 5.0,
        },
        "dispatch-ozon-analytics": {"task": "perk.ozon.analytics.dispatch", "schedule": 5.0},
        "dispatch-ozon-catalog": {"task": "perk.ozon.catalog.dispatch", "schedule": 5.0},
        "dispatch-wb-sync": {"task": "perk.sync.dispatch", "schedule": 2.0},
        "schedule-wb-sync": {"task": "perk.sync.schedule", "schedule": 5.0},
        "warm-wb-analytics": {"task": "perk.analytics.warm", "schedule": 300.0},
        # Precomputed screens; a fresh snapshot costs one cheap revision check.
        "warm-insights": {"task": "perk.insights.warm", "schedule": 900.0},
        "maintenance-cleanup": {"task": "perk.maintenance.cleanup", "schedule": 21600.0},
        "notifications-dispatch": {"task": "perk.notifications.dispatch", "schedule": 300.0},
    },
)


def tag_handlers(logger, *args, **kwargs):
    """Worker logs carry the task id in the same slot as the API's request id."""
    # Celery configures logging separately from the API. Signed export URLs must stay private.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    for handler in logger.handlers:
        handler.addFilter(RequestIdFilter())
        handler.setFormatter(logging.Formatter(FORMAT))


after_setup_logger.connect(tag_handlers)
after_setup_task_logger.connect(tag_handlers)
TASK_TOKENS = {}


@before_task_publish.connect
def propagate_request_id(headers=None, **kwargs):
    """Keep the HTTP request id across queued jobs and their downstream jobs."""
    if headers is not None and request_id.get() != "-":
        headers["perk_request_id"] = request_id.get()


@task_prerun.connect
def bind_task_id(task_id=None, task=None, **kwargs):
    headers = getattr(getattr(task, "request", None), "headers", None) or {}
    origin = headers.get("perk_request_id") or f"task-{task_id}"
    TASK_TOKENS[task_id] = (request_id.set(origin), current_task_id.set(task_id or "-"))


@task_postrun.connect
def unbind_task_id(task_id=None, **kwargs):
    tokens = TASK_TOKENS.pop(task_id, None)
    if tokens is not None:
        request_id.reset(tokens[0])
        current_task_id.reset(tokens[1])
