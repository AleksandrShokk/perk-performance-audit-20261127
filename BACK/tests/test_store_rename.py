from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.modules.accounts import router
from app.modules.accounts.schemas import RenameStoreInput


@pytest.mark.parametrize("name", ["", " ", "x" * 101])
def test_name_is_nonempty_and_bounded(name):
    with pytest.raises(ValidationError):
        RenameStoreInput(name=name)


def test_name_input_rejects_secret_or_identity_fields():
    with pytest.raises(ValidationError):
        RenameStoreInput(name="Store", token="secret")


def test_rename_scopes_the_lookup_and_keeps_store_identity(monkeypatch):
    wid, sid = uuid4(), uuid4()
    store = SimpleNamespace(id=sid, name="Before", marketplace="ozon", external_seller_id="123")
    calls = []
    monkeypatch.setattr(
        router,
        "require_workspace",
        lambda db, identity, workspace, owner=False: calls.append((workspace, owner)),
    )

    def find(db, workspace, selected):
        assert (workspace, selected) == (wid, sid)
        return store

    monkeypatch.setattr(router, "find_store", find)
    monkeypatch.setattr(router, "audit", lambda *args, **kwargs: None)
    db = SimpleNamespace(commit=lambda: calls.append("commit"))
    identity = SimpleNamespace(user=SimpleNamespace(id=uuid4()))
    result = router.rename_store(wid, sid, RenameStoreInput(name="  New name  "), db, identity)
    assert result.name == "New name" and result.id == sid and result.external_seller_id == "123"
    assert calls == [(wid, True), "commit"]


def test_non_admin_cannot_reach_store_lookup(monkeypatch):
    def denied(*args, **kwargs):
        raise HTTPException(404)

    monkeypatch.setattr(router, "require_workspace", denied)
    monkeypatch.setattr(router, "find_store", lambda *args: pytest.fail("Forbidden lookup"))
    with pytest.raises(HTTPException):
        router.rename_store(uuid4(), uuid4(), RenameStoreInput(name="New"), None, None)
