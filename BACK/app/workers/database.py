"""One database pool per worker process; never share live connections across forks."""

import os

from celery.signals import worker_process_shutdown, worker_shutdown

from app.db.session import build_engine

_pools = {}


def worker_engine(settings):
    key = (os.getpid(), settings.database_url)
    if key not in _pools:
        _pools[key] = build_engine(settings)
    return _pools[key]


def release_engine(engine):
    # Test-injected/noncached engines retain their normal lifecycle.
    if engine not in _pools.values():
        engine.dispose()


@worker_process_shutdown.connect
@worker_shutdown.connect
def close_pools(**kwargs):
    for engine in _pools.values():
        engine.dispose()
    _pools.clear()
