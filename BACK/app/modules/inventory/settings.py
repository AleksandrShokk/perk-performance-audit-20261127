from typing import Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict
from sqlalchemy.dialects.postgresql import insert

from app.modules.accounts.access import require_permission
from app.modules.accounts.router import require_workspace
from app.modules.audit.service import audit
from app.modules.auth.dependencies import DB, FullIdentity, now
from app.modules.inventory.settings_models import InventorySettings

router = APIRouter(prefix="/workspaces/{workspace_id}/inventory", tags=["Inventory"])


class InventorySettingsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fbs_mode: Literal["separate", "shared"]


class InventorySettingsView(BaseModel):
    fbs_mode: Literal["separate", "shared", "unknown"]


def fbs_mode(db, workspace_id):
    row = db.get(InventorySettings, workspace_id)
    return row.fbs_mode if row else "unknown"


@router.get("/settings", response_model=InventorySettingsView, operation_id="inventorySettingsGet")
def settings(workspace_id: UUID, db: DB, identity: FullIdentity):
    require_permission(db, identity, workspace_id, "inventory.read")
    return InventorySettingsView(fbs_mode=fbs_mode(db, workspace_id))


@router.put("/settings", response_model=InventorySettingsView, operation_id="inventorySettingsSave")
def save_settings(workspace_id: UUID, data: InventorySettingsInput, db: DB, identity: FullIdentity):
    require_workspace(db, identity, workspace_id, owner=True)
    statement = insert(InventorySettings).values(
        workspace_id=workspace_id,
        fbs_mode=data.fbs_mode,
        updated_by=identity.user.id,
        updated_at=now(),
    )
    db.execute(
        statement.on_conflict_do_update(
            index_elements=["workspace_id"],
            set_={"fbs_mode": data.fbs_mode, "updated_by": identity.user.id, "updated_at": now()},
        )
    )
    audit(db, "inventory.settings_saved", user_id=identity.user.id, workspace_id=workspace_id)
    db.commit()
    return InventorySettingsView(fbs_mode=data.fbs_mode)
