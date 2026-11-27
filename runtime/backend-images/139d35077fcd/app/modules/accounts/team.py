"""Email-bound invitations and editable employee access. The creator is protected."""

from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator
from sqlalchemy import delete, select, text

from app.integrations.email_templates import invitation_email
from app.integrations.notifications import DeliveryError
from app.modules.accounts.access import FULL_ROLES, PERMISSIONS, effective, normalize_permissions
from app.modules.accounts.models import Store, Workspace, WorkspaceInvite
from app.modules.accounts.router import require_workspace
from app.modules.accounts.team_links import invitation_link
from app.modules.audit.service import audit
from app.modules.auth.dependencies import (
    DB,
    FullIdentity,
    RecentIdentity,
    StrongIdentity,
    now,
    strong_identity,
)
from app.modules.auth.models import Membership, User
from app.modules.auth.schemas import MessageResponse
from app.security.crypto import new_token
from app.security.limits import rate_limit

router = APIRouter(tags=["Team"])
Role = Literal["owner", "admin", "manager", "accountant", "viewer"]
INVITE_TTL = timedelta(days=7)
ROLE_LABELS = {
    "owner": "Владелец",
    "admin": "Администратор",
    "manager": "Менеджер",
    "accountant": "Бухгалтер",
    "viewer": "Наблюдатель",
}


class AccessInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Role = "viewer"
    permissions: list[str] | None = Field(default=None, max_length=30)
    store_ids: list[UUID] | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def validate_access(self):
        if self.permissions is not None and set(self.permissions) - PERMISSIONS.keys():
            raise ValueError("Неизвестное право доступа")
        if self.role in FULL_ROLES:
            self.permissions = self.store_ids = None
        elif self.permissions is not None:
            self.permissions = normalize_permissions(self.permissions)
        return self


class InviteInput(AccessInput):
    email: EmailStr


class RoleInput(AccessInput):
    pass


class MemberView(BaseModel):
    user_id: UUID
    email: str
    role: Role
    permissions: list[str]
    store_ids: list[str] | None
    is_creator: bool


class InviteView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    email: str
    role: Role
    permissions: list[str] | None
    store_ids: list[str] | None
    expires_at: datetime
    created_at: datetime


class Team(BaseModel):
    members: list[MemberView]
    invites: list[InviteView]


class AcceptInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=20, max_length=100)


class InviteDetails(BaseModel):
    email: str
    workspace_name: str
    role: Role
    permissions: list[str] | None
    store_ids: list[str] | None
    expires_at: datetime


class Accepted(BaseModel):
    workspace_id: UUID


def invalid_invite():
    return HTTPException(
        404,
        {
            "code": "invite_invalid",
            "message": "Приглашение недействительно, истекло или отправлено на другой адрес.",
        },
    )


def invite_details(db, vault, code):
    value = db.scalar(
        text("SELECT perk_invite_details(:digest)"),
        {"digest": vault.digest("team-invite", code.strip())},
    )
    if not value:
        raise invalid_invite()
    return value


@router.post("/invites/preview", response_model=InviteDetails, operation_id="teamPreviewInvite")
def preview(data: AcceptInput, request: Request, db: DB):
    rate_limit(
        request.app.state.redis,
        request.app.state.vault,
        "invite-preview",
        request.client.host if request.client else "unknown",
        60,
        3600,
    )
    return invite_details(db, request.app.state.vault, data.code)


def member_view(member, email, creator):
    return MemberView(
        user_id=member.user_id,
        email=email,
        role=member.role,
        permissions=effective(member),
        store_ids=member.store_ids,
        is_creator=creator,
    )


@router.get("/workspaces/{workspace_id}/team", response_model=Team, operation_id="teamList")
def team(workspace_id: UUID, db: DB, identity: FullIdentity):
    require_workspace(db, identity, workspace_id, owner=True)
    workspace = db.get(Workspace, workspace_id)
    rows = db.execute(
        select(Membership, User.email)
        .join(User, User.id == Membership.user_id)
        .where(Membership.workspace_id == workspace_id)
        .order_by(User.email)
    ).all()
    invites = db.scalars(
        select(WorkspaceInvite)
        .where(
            WorkspaceInvite.workspace_id == workspace_id,
            WorkspaceInvite.accepted_at.is_(None),
            WorkspaceInvite.expires_at > now(),
        )
        .order_by(WorkspaceInvite.created_at)
    ).all()
    return Team(
        members=[
            member_view(member, email, member.user_id == workspace.owner_user_id)
            for member, email in rows
        ],
        invites=invites,
    )


def access_values(db, workspace_id, data):
    store_ids = None if data.store_ids is None else sorted({str(value) for value in data.store_ids})
    if store_ids:
        found = db.scalars(
            select(Store.id).where(
                Store.workspace_id == workspace_id,
                Store.is_active.is_(True),
                Store.id.in_(data.store_ids),
            )
        ).all()
        if {str(value) for value in found} != set(store_ids):
            raise HTTPException(422, "Выберите магазины этого кабинета.")
    return dict(role=data.role, permissions=data.permissions, store_ids=store_ids)


def send_invitation(request, row, workspace, code):
    # A fragment keeps the invitation secret out of frontend HTTP request logs/referrers.
    link = invitation_link(request.app.state.settings, request.headers.get("origin"), code)
    body, html = invitation_email(workspace.name, ROLE_LABELS[row.role], row.email, link)
    try:
        request.app.state.notifier.send_email(
            row.email,
            "Приглашение в команду PERK",
            body,
            html=html,
        )
    except DeliveryError:
        raise HTTPException(
            503,
            {
                "code": "email_unavailable",
                "message": "Приглашение сохранено, но письмо не отправлено. Повторите отправку.",
            },
        ) from None


@router.post(
    "/workspaces/{workspace_id}/invites",
    response_model=InviteView,
    status_code=201,
    operation_id="teamInvite",
)
def invite(
    workspace_id: UUID, data: InviteInput, request: Request, db: DB, identity: RecentIdentity
):
    require_workspace(db, identity, workspace_id, owner=True)
    if data.role in FULL_ROLES:
        strong_identity(identity)
    state = request.app.state
    rate_limit(state.redis, state.vault, "team-invite", str(workspace_id), 20, 86400)
    email = str(data.email).strip().lower()
    if db.scalar(
        select(User.id)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.workspace_id == workspace_id, User.email == email)
    ):
        raise HTTPException(409, {"code": "already_member", "message": "Сотрудник уже в команде."})
    values = access_values(db, workspace_id, data)
    db.execute(
        delete(WorkspaceInvite).where(
            WorkspaceInvite.workspace_id == workspace_id,
            WorkspaceInvite.email == email,
            WorkspaceInvite.accepted_at.is_(None),
        )
    )
    code = new_token("pw_")
    row = WorkspaceInvite(
        workspace_id=workspace_id,
        email=email,
        **values,
        token_digest=state.vault.digest("team-invite", code),
        invited_by=identity.user.id,
        expires_at=now() + INVITE_TTL,
    )
    db.add(row)
    db.flush()
    workspace = db.get(Workspace, workspace_id)
    audit(db, "team.invited", user_id=identity.user.id, workspace_id=workspace_id, target_id=row.id)
    db.commit()
    send_invitation(request, row, workspace, code)
    return row


@router.post(
    "/workspaces/{workspace_id}/invites/{invite_id}/resend",
    response_model=InviteView,
    operation_id="teamResendInvite",
)
def resend(workspace_id: UUID, invite_id: UUID, request: Request, db: DB, identity: RecentIdentity):
    require_workspace(db, identity, workspace_id, owner=True)
    row = db.scalar(
        select(WorkspaceInvite)
        .where(
            WorkspaceInvite.workspace_id == workspace_id,
            WorkspaceInvite.id == invite_id,
            WorkspaceInvite.accepted_at.is_(None),
        )
        .with_for_update()
    )
    if not row:
        raise HTTPException(404, "Приглашение не найдено.")
    if row.role in FULL_ROLES:
        strong_identity(identity)
    state = request.app.state
    rate_limit(state.redis, state.vault, "team-resend", str(row.id), 3, 3600)
    code = new_token("pw_")
    row.token_digest = state.vault.digest("team-invite", code)
    row.expires_at, row.invited_by = now() + INVITE_TTL, identity.user.id
    workspace = db.get(Workspace, workspace_id)
    audit(
        db,
        "team.invite_resent",
        user_id=identity.user.id,
        workspace_id=workspace_id,
        target_id=row.id,
    )
    db.commit()
    send_invitation(request, row, workspace, code)
    return row


@router.delete(
    "/workspaces/{workspace_id}/invites/{invite_id}",
    status_code=204,
    operation_id="teamCancelInvite",
)
def cancel_invite(workspace_id: UUID, invite_id: UUID, db: DB, identity: FullIdentity):
    require_workspace(db, identity, workspace_id, owner=True)
    row = db.scalar(
        select(WorkspaceInvite).where(
            WorkspaceInvite.id == invite_id, WorkspaceInvite.workspace_id == workspace_id
        )
    )
    if row:
        db.delete(row)
        audit(db, "team.invite_cancelled", user_id=identity.user.id, workspace_id=workspace_id)
        db.commit()


@router.post("/invites/accept", response_model=Accepted, operation_id="teamAcceptInvite")
def accept(data: AcceptInput, request: Request, db: DB, identity: FullIdentity):
    state = request.app.state
    rate_limit(state.redis, state.vault, "team-accept", str(identity.user.id), 10, 3600)
    details = invite_details(db, state.vault, data.code)
    if details["email"] != identity.user.email:
        raise invalid_invite()
    if not identity.user.phone or not identity.user.phone_verified_at:
        raise HTTPException(
            403,
            {
                "code": "phone_required",
                "message": "Подтвердите номер телефона перед вступлением в команду.",
            },
        )
    workspace_id = db.scalar(
        text("SELECT perk_accept_invite(:digest)"),
        {"digest": state.vault.digest("team-invite", data.code.strip())},
    )
    if workspace_id is None:
        raise invalid_invite()
    audit(db, "team.joined", user_id=identity.user.id, workspace_id=workspace_id)
    db.commit()
    return Accepted(workspace_id=workspace_id)


def editable_member(db, workspace_id, user_id):
    workspace = db.get(Workspace, workspace_id)
    membership = db.get(Membership, (user_id, workspace_id))
    if not membership:
        raise HTTPException(404, "Участник не найден.")
    if user_id == workspace.owner_user_id:
        raise HTTPException(
            409, {"code": "creator_protected", "message": "Создателя кабинета нельзя изменить."}
        )
    return membership


@router.put(
    "/workspaces/{workspace_id}/members/{user_id}",
    response_model=MemberView,
    operation_id="teamChangeRole",
)
def change_role(
    workspace_id: UUID, user_id: UUID, data: RoleInput, db: DB, identity: StrongIdentity
):
    require_workspace(db, identity, workspace_id, owner=True)
    membership = editable_member(db, workspace_id, user_id)
    for key, value in access_values(db, workspace_id, data).items():
        setattr(membership, key, value)
    audit(
        db,
        "team.role_changed",
        user_id=identity.user.id,
        workspace_id=workspace_id,
        target_id=user_id,
    )
    db.commit()
    return member_view(membership, db.get(User, user_id).email, False)


@router.delete(
    "/workspaces/{workspace_id}/members/{user_id}",
    response_model=MessageResponse,
    operation_id="teamRemoveMember",
)
def remove_member(workspace_id: UUID, user_id: UUID, db: DB, identity: FullIdentity):
    require_workspace(db, identity, workspace_id, owner=user_id != identity.user.id)
    membership = editable_member(db, workspace_id, user_id)
    audit(
        db,
        "team.member_removed",
        user_id=identity.user.id,
        workspace_id=workspace_id,
        target_id=user_id,
    )
    db.flush()
    db.delete(membership)
    db.commit()
    return MessageResponse(message="Участник удалён из команды")
