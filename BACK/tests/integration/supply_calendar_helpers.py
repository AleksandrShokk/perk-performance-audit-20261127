import json
from datetime import timedelta

from sqlalchemy.orm import Session

from app.modules.auth.dependencies import now
from app.modules.insights.marketplace_models import MarketplaceSalesDay
from app.modules.insights.ozon_jobs import sales_aad
from app.modules.sync.schemas import moscow_today


def publish_orders(e, sid, fbo=None, fbs=None, days=28):
    end = moscow_today() - timedelta(days=1)
    with Session(e.admin) as db, db.begin():
        for offset in range(days):
            day = end - timedelta(days=offset)
            value = {
                "channel_orders": {
                    "fbo": fbo if offset == 0 else {},
                    "fbs": fbs if offset == 0 else {},
                }
            }
            payload = e.vault.seal(json.dumps(value), sales_aad(e.workspace, sid, day))
            row = db.get(MarketplaceSalesDay, (e.workspace, sid, day))
            if row:
                row.ciphertext = payload
                row.updated_at = now()
            else:
                db.add(
                    MarketplaceSalesDay(
                        workspace_id=e.workspace,
                        store_id=sid,
                        day=day,
                        ciphertext=payload,
                        updated_at=now(),
                    )
                )
