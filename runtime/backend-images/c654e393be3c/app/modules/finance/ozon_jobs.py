"""Finance branch of the secured Ozon outbox; complete days published atomically."""

import json
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.session import set_actor
from app.integrations.ozon.finance import FinanceClient
from app.integrations.ozon.transport import OzonImportError
from app.modules.accounts.ozon_connection import credential_row, open_credentials
from app.modules.auth.dependencies import now
from app.modules.catalog.ozon_jobs import authorized
from app.modules.finance import ozon_facts, realizations
from app.modules.finance.marketplace_models import MarketplaceFinanceDay, MarketplaceRealization
from app.modules.insights.marketplace_models import OzonAnalyticsSync


def aad(workspace_id, store_id, day):
    return f"perk-marketplace-finance:v1:{workspace_id}:{store_id}:{day}"


def execute(engine, vault, wid, sid, actor, run_id, client_factory=FinanceClient):
    key = (wid, sid, "finance")
    with Session(engine) as db, db.begin():
        store = authorized(db, wid, sid, actor)
        if not store:
            from app.workers.outbox import reject_ozon

            reject_ozon(db, wid, sid, "finance", actor, run_id)
            return
        job = db.get(OzonAnalyticsSync, key, with_for_update=True)
        if not job or job.run_id != run_id or job.status != "queued":
            return
        credential = credential_row(db, store)
        original = credential.ciphertext
        secret = open_credentials(vault, store, credential)
        start, end, mode = job.date_from, job.date_to, job.mode
        job.status, job.records_processed = "running", 0
        job.next_attempt_at = now() + timedelta(minutes=12)

    def progress(count):
        with Session(engine) as db, db.begin():
            set_actor(db, actor)
            current = db.get(OzonAnalyticsSync, key, with_for_update=True)
            if not current or current.run_id != run_id or current.status != "running":
                raise OzonImportError("import_replaced", 30)
            current.records_processed = count

    client = client_factory(secret["client_id"], secret["api_key"])
    days, count = client.days(start, end, ozon_facts.normalize_partial, progress)
    if set(days) != {start + timedelta(days=i) for i in range((end - start).days + 1)}:
        raise OzonImportError("ozon_incomplete_period")
    with Session(engine) as db, db.begin():
        store = authorized(db, wid, sid, actor)
        if not store:
            raise OzonImportError("access_revoked", 21600)
        db.refresh(store, with_for_update=True)
        job = db.get(OzonAnalyticsSync, key, with_for_update=True)
        if not job or job.run_id != run_id or job.status != "running":
            return
        if (
            credential_row(db, store).ciphertext != original
            or not store.is_active
            or store.connection_status != "connected"
        ):
            raise OzonImportError("credential_changed", 30)
        stamp = now()
        for day, facts in days.items():
            from app.modules.sync.issues import retain

            for issue in facts.get("issues", []):
                retain(db, vault, wid, sid, "ozon_finance", issue["record_id"], issue["reason"])
            # Replace a whole day, including corrections and removed charges/prices.
            price_rows = facts.pop("realizations")
            for value in facts.get("cost_items", []):
                value["key"] = realizations.posting_key(vault, wid, sid, value["key"])
            statement = insert(MarketplaceFinanceDay).values(
                workspace_id=wid,
                store_id=sid,
                day=day,
                updated_at=stamp,
                ciphertext=vault.seal(json.dumps(facts), aad(wid, sid, day)),
            )
            db.execute(
                statement.on_conflict_do_update(
                    index_elements=["workspace_id", "store_id", "day"],
                    set_={"ciphertext": statement.excluded.ciphertext, "updated_at": stamp},
                )
            )
            db.execute(
                delete(MarketplaceRealization).where(
                    MarketplaceRealization.workspace_id == wid,
                    MarketplaceRealization.store_id == sid,
                    MarketplaceRealization.day == day,
                )
            )
            prices = defaultdict(set)
            for value in price_rows:
                hashed = realizations.posting_key(vault, wid, sid, value["number"])
                prices[(hashed, value["sku"])].add((value["price"], value["currency"]))
            for (hashed, sku), candidates in prices.items():
                price, currency = next(iter(candidates)) if len(candidates) == 1 else (None, None)
                db.add(
                    MarketplaceRealization(
                        workspace_id=wid,
                        store_id=sid,
                        day=day,
                        posting_key=hashed,
                        sku=sku,
                        ciphertext=vault.seal(
                            json.dumps({"price": price, "currency": currency}),
                            realizations.aad(wid, sid, day, hashed, sku),
                        ),
                    )
                )
        if mode == "history":
            job.cursor = start - timedelta(days=1) if start > job.history_from else None
        job.status, job.error_code, job.records_processed = "ready", None, count
        job.updated_at = stamp
        job.next_attempt_at = stamp if job.cursor is not None else stamp + timedelta(hours=6)
