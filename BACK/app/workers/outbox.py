"""A bounded, metadata-only discovery function; subsequent reads/writes use tenant RLS."""

from sqlalchemy import text

from app.db.session import set_actor


def actors(db, queue):
    rows = db.scalars(text("SELECT perk_queue_actors(:queue)"), {"queue": queue}).all()
    for actor in rows:
        set_actor(db, actor)
        yield actor
        db.flush()


def bind_sync(db, run_id, task_id):
    actor = db.scalar(text("SELECT perk_sync_actor(:run, :task)"), {"run": run_id, "task": task_id})
    if actor:
        set_actor(db, actor)
    return actor


def reject_ozon(db, wid, sid, source, actor, run):
    db.execute(
        text("SELECT perk_reject_ozon_job(:ws,:sid,:src,:actor,:run)"),
        {"ws": wid, "sid": sid, "src": source, "actor": actor, "run": run},
    )
