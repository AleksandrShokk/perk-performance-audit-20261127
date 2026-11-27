from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.modules.accounts.reporting import require_reporting_store
from app.modules.accounts.router import find_store, require_workspace
from app.modules.audit.service import audit
from app.modules.auth.dependencies import DB, FullIdentity, now
from app.modules.supplies.models import SupplyPackaging

router = APIRouter(
    prefix="/workspaces/{workspace_id}/stores/{store_id}/inventory", tags=["Inventory"]
)


class PackagingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    box_multiple: int = Field(ge=1, le=10000, strict=True)


class PackagingView(PackagingInput):
    product_key: str


def product_key(item):
    return item.id or item.nm_id


def multiples(db, workspace_id, stores):
    if not stores:
        return {}
    rows = db.scalars(
        select(SupplyPackaging).where(
            SupplyPackaging.workspace_id == workspace_id,
            SupplyPackaging.store_id.in_([store.id for store in stores]),
        )
    )
    return {(str(row.store_id), row.product_key): row.box_multiple for row in rows}


def apply(items, values):
    result = []
    for item in items:
        multiple = values.get((str(item.store_id), product_key(item)), 1)
        quantity = ((item.quantity + multiple - 1) // multiple) * multiple
        result.append(
            item.model_copy(
                update={
                    "box_multiple": multiple,
                    "required_quantity": item.quantity,
                    "quantity": quantity,
                }
            )
        )
    return result


@router.put(
    "/packaging/{product_key}", response_model=PackagingView, operation_id="inventoryPackagingSave"
)
def save_packaging(
    workspace_id: UUID,
    store_id: UUID,
    product_key: Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,100}$")],
    data: PackagingInput,
    db: DB,
    identity: FullIdentity,
):
    require_workspace(db, identity, workspace_id, owner=True)
    require_reporting_store(find_store(db, workspace_id, store_id), "supplies")
    values = dict(
        workspace_id=workspace_id,
        store_id=store_id,
        product_key=product_key,
        box_multiple=data.box_multiple,
        updated_by=identity.user.id,
        updated_at=now(),
    )
    statement = insert(SupplyPackaging).values(**values)
    db.execute(
        statement.on_conflict_do_update(
            index_elements=["workspace_id", "store_id", "product_key"],
            set_={key: values[key] for key in ("box_multiple", "updated_by", "updated_at")},
        )
    )
    audit(
        db,
        "inventory.packaging_saved",
        user_id=identity.user.id,
        workspace_id=workspace_id,
        target_id=store_id,
    )
    db.commit()
    return PackagingView(product_key=product_key, box_multiple=data.box_multiple)
