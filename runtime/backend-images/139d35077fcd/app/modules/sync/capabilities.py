from cryptography.exceptions import InvalidTag
from fastapi import HTTPException

from app.integrations.wildberries.client import inspect_token
from app.integrations.wildberries.data import SCOPES, Source
from app.modules.sync.schemas import history_limits

TOKEN_TYPES = {1: "basic", 3: "personal", 4: "service"}


def sync_capabilities(credential, vault, settings, workspace_id, store_id):
    """Only non-secret access metadata; never return or log a WB credential."""
    try:
        if not credential:
            raise ValueError
        token = vault.open(credential.ciphertext, f"wb:{workspace_id}:{store_id}")
        metadata = inspect_token(
            token,
            production=settings.app_env == "production",
            service_id=settings.wb_service_id,
            allow_personal=settings.allows_personal_wb_token(workspace_id),
        )
    except HTTPException, InvalidTag, ValueError:
        return {
            # Public status label; no credential value is returned.
            "token_type": "unavailable",  # nosec B105
            "sources": {
                s: {"available": False, "error_code": "credential_unavailable"} for s in Source
            },
            "history_limits": history_limits(),
        }
    sources = {}
    for source in Source:
        error = None
        if SCOPES[source] not in metadata.scopes:
            error = "wb_scope_missing"
        elif source == Source.STOCKS and metadata.token_type not in {3, 4}:
            error = "wb_token_type_unsupported"
        sources[source] = {"available": error is None, "error_code": error}
    return {
        "token_type": TOKEN_TYPES[metadata.token_type],
        "sources": sources,
        "history_limits": history_limits(),
    }
