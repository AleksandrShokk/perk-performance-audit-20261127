from collections.abc import Iterator

from fastapi import HTTPException, Request
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.config import Settings


def build_engine(settings: Settings) -> Engine:
    engine = create_engine(
        settings.database_url,
        hide_parameters=True,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        pool_timeout=3,
        connect_args={
            "connect_timeout": 3,
            "options": "-c statement_timeout=5000 -c timezone=UTC",
        },
    )

    @event.listens_for(engine, "connect")
    def inspect_role(connection, record):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user"
            )
            record.info["runtime_privileged"] = cursor.fetchone()[0]
        connection.rollback()

    return engine


def get_db(request: Request) -> Iterator[Session]:
    with Session(request.app.state.db_engine, expire_on_commit=False) as session:
        privileged = session.connection().info.get("runtime_privileged", True)
        if privileged:
            raise HTTPException(503, "Сервис временно недоступен. Попробуйте позже.")
        yield session


def set_actor(session: Session, user_id) -> None:
    # Transaction-local: pooled connections cannot retain the previous user's identity.
    session.execute(
        text("SELECT set_config('perk.user_id', :value, true)"), {"value": str(user_id)}
    )
