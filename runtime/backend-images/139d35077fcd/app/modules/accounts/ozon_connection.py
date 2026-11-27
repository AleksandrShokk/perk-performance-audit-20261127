"""Encrypted Seller credentials, independent from WB token format and AAD."""

import json

from cryptography.exceptions import InvalidTag
from fastapi import HTTPException
from sqlalchemy import select

from app.integrations.ozon.client import failure
from app.modules.accounts.models import StoreCredential
from app.modules.accounts.schemas import ConnectionResponse
from app.modules.audit.service import audit
from app.modules.auth.dependencies import now
from app.security.limits import rate_limit


def credential_aad(workspace_id, store_id):
    return f"ozon-seller:v1:{workspace_id}:{store_id}"


def credential_row(db, store):
    row = db.scalar(
        select(StoreCredential).where(
            StoreCredential.workspace_id == store.workspace_id, StoreCredential.store_id == store.id
        )
    )
    if not row:
        raise HTTPException(400, "Магазин отключён. Подключите его заново.")
    return row


def verify(request, client_id, api_key):
    rate_limit(
        request.app.state.redis,
        request.app.state.vault,
        "ozon-key-check",
        f"{client_id}:{api_key}",
        5,
        60,
    )
    return request.app.state.ozon_client.verify(client_id, api_key)


def seal(vault, store, client_id, api_key, access):
    return vault.seal(
        json.dumps(
            {
                "client_id": client_id,
                "api_key": api_key,
                "roles": access.roles,
                "methods": access.methods,
            }
        ),
        credential_aad(store.workspace_id, store.id),
    )


def open_credentials(vault, store, row):
    try:
        data = json.loads(vault.open(row.ciphertext, credential_aad(store.workspace_id, store.id)))
        if data["client_id"] != store.external_seller_id or not isinstance(data["api_key"], str):
            raise ValueError("identity")
        return data
    except InvalidTag, ValueError, KeyError, TypeError:
        raise failure(
            503, "credential_unavailable", "Не удалось прочитать подключение Ozon."
        ) from None


def check(request, db, identity, store):
    row = credential_row(db, store)
    original = row.ciphertext
    secret = open_credentials(request.app.state.vault, store, row)
    problem = None
    try:
        access = verify(request, secret["client_id"], secret["api_key"])
    except HTTPException as exc:
        if exc.status_code != 400:
            raise
        problem = exc
    # A stale check must not overwrite the status of a concurrently replaced key.
    db.refresh(store, with_for_update=True)
    db.refresh(row)
    if row.ciphertext != original:
        raise failure(409, "credential_changed", "Ключ уже обновлён. Повторите проверку.")
    store.last_checked_at = now()
    if problem:
        store.connection_status = "invalid_token"
    else:
        store.connection_status = "connected"
        row.expires_at = access.expires_at
        row.ciphertext = seal(
            request.app.state.vault, store, secret["client_id"], secret["api_key"], access
        )
    audit(
        db,
        "store.check_failed" if problem else "store.checked",
        user_id=identity.user.id,
        workspace_id=store.workspace_id,
        target_id=store.id,
        success=not problem,
    )
    db.commit()
    if problem:
        raise problem
    return ConnectionResponse(
        status="connected",
        scopes=["seller_api"],
        expires_at=row.expires_at,
        checked_at=store.last_checked_at,
        client_id=store.external_seller_id,
    )
