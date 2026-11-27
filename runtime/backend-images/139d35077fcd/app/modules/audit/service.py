from uuid import uuid4

from sqlalchemy import insert

from app.modules.audit.models import AuditEvent


def audit(db, action, user_id=None, workspace_id=None, target_id=None, success=True):
    # No RETURNING: an unauthenticated login attempt may append an event but must not
    # SELECT anonymous audit rows. ORM eager defaults would require that read permission.
    db.execute(
        insert(AuditEvent)
        .inline()
        .values(
            id=uuid4(),
            action=action,
            user_id=user_id,
            workspace_id=workspace_id,
            target_id=target_id,
            success=success,
        )
    )
