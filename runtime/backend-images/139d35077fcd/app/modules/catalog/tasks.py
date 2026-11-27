import json
import logging
from uuid import UUID

from celery.exceptions import Retry
from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import set_actor
from app.integrations.wildberries.client import inspect_token
from app.integrations.wildberries.data import Source, WBDataClient, WBError
from app.modules.accounts.models import Store, StoreCredential
from app.modules.auth.models import Membership, User
from app.modules.catalog.metadata import cached_definitions, definitions, schema_key
from app.modules.sync.quota import gate_key
from app.modules.sync.read import retained
from app.security.crypto import SecretVault
from app.workers.celery_app import celery_app
from app.workers.database import release_engine
from app.workers.database import worker_engine as build_engine

logger = logging.getLogger(__name__)


def resources():
    settings = get_settings()
    return (
        settings,
        build_engine(settings),
        Redis.from_url(
            settings.redis_broker_url,
            decode_responses=True,
            socket_timeout=3,
            socket_connect_timeout=3,
        ),
        SecretVault(settings.security_file),
    )


def credentials(db, vault, settings, workspace_id, store_id, actor_id):
    workspace_id, store_id, actor_id = UUID(workspace_id), UUID(store_id), UUID(actor_id)
    set_actor(db, actor_id)
    member = db.get(Membership, (actor_id, workspace_id))
    user = db.get(User, actor_id)
    store = db.get(Store, store_id)
    if (
        not member
        or member.role not in {"owner", "admin"}
        or not user
        or not user.is_active
        or not user.email_verified_at
    ):
        return None
    if (
        not store
        or store.workspace_id != workspace_id
        or not store.is_active
        or store.connection_status != "connected"
        or store.marketplace != "wildberries"
    ):
        return None
    credential = db.scalar(
        select(StoreCredential).where(
            StoreCredential.workspace_id == workspace_id, StoreCredential.store_id == store_id
        )
    )
    if not credential or "content" not in credential.scopes.split(","):
        return None
    token = vault.open(credential.ciphertext, f"wb:{workspace_id}:{store_id}")
    info = inspect_token(
        token,
        production=settings.app_env == "production",
        service_id=settings.wb_service_id,
        allow_personal=settings.allows_personal_wb_token(workspace_id),
    )
    if info.seller_id != store.external_seller_id:
        return None
    return token, info


@celery_app.task(name="perk.catalog.schemas", ignore_result=True, soft_time_limit=45, time_limit=55)
def queue_schemas(workspace_id, store_id, actor_id):
    settings, engine, redis, vault = resources()
    try:
        with Session(engine) as db:
            if not credentials(db, vault, settings, workspace_id, store_id, actor_id):
                return
            categories = {
                card.get("category_id", "")
                for card in retained(db, vault, UUID(workspace_id), UUID(store_id), Source.CATALOG)
            }
            cached = cached_definitions(redis, categories)
        for index, category in enumerate(sorted(categories - cached.keys())):
            if str(category).isdigit():
                fetch_schema.apply_async(
                    args=[workspace_id, store_id, actor_id, category],
                    countdown=index * 2,
                    retry=False,
                )
    except Exception:
        logger.error("catalog_schema_queue_unavailable")
    finally:
        redis.close()
        release_engine(engine)


@celery_app.task(
    bind=True,
    name="perk.catalog.schema",
    ignore_result=True,
    max_retries=8,
    soft_time_limit=40,
    time_limit=50,
)
def fetch_schema(self, workspace_id, store_id, actor_id, category):
    settings, engine, redis, vault = resources()
    gate = None
    try:
        if category in cached_definitions(redis, [category]):
            return
        with Session(engine) as db:
            credential = credentials(db, vault, settings, workspace_id, store_id, actor_id)
            if not credential:
                return
            token, info = credential
            gate = gate_key(redis, vault, Source.CATALOG, info)
            if not redis.set(gate, "1", nx=True, ex=2):
                raise self.retry(countdown=max(2, redis.ttl(gate)))
            client = WBDataClient()
            values = definitions(client.category_schema(token, category))
            if client.cooldown_seconds:
                redis.expire(gate, max(2, client.cooldown_seconds))
            redis.set(schema_key(category), json.dumps(values), ex=7 * 86400)
    except Retry:
        raise
    except WBError as error:
        if gate and error.retry_after:
            redis.expire(gate, error.retry_after)
        if error.retryable:
            raise self.retry(countdown=max(10, error.retry_after)) from None
        logger.error("catalog_schema_provider_unavailable")
    except Exception:
        logger.error("catalog_schema_unavailable")
    finally:
        redis.close()
        release_engine(engine)
