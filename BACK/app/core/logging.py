import logging
from logging.config import dictConfig

FORMAT = "%(asctime)s %(levelname)s %(name)s [%(request_id)s task=%(task_id)s] %(message)s"


def configure_logging(level: str) -> None:
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {"request_id": {"()": "app.core.errors.RequestIdFilter"}},
            "formatters": {"default": {"format": FORMAT}},
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                    "filters": ["request_id"],
                }
            },
            "root": {"level": level, "handlers": ["console"]},
        }
    )
    # HTTP client logs can contain request URLs; keep them out of routine output.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
