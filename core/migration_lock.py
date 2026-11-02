import logging
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Connection, text

MIGRATION_LOCK_ID = 7_294_015_133


def _try_lock(connection: Connection) -> bool:
    return bool(
        connection.execute(
            text("SELECT pg_try_advisory_lock(:id)"), {"id": MIGRATION_LOCK_ID}
        ).scalar()
    )


@contextmanager
def migration_lock(connection: Connection, log: logging.Logger) -> Iterator[None]:
    """Hold a Postgres session advisory lock so only one process migrates at a time.

    The lock query autobegins a transaction. It is committed straight away, because
    alembic's `begin_transaction()` won't commit a transaction it didn't open, and the
    migrations would be rolled back when the connection closes. A session lock outlives
    that commit, and Postgres drops it with the connection if the process dies.
    """
    if not _try_lock(connection):
        log.info("Another process is running migrations, waiting for it to finish")
        connection.execute(
            text("SELECT pg_advisory_lock(:id)"), {"id": MIGRATION_LOCK_ID}
        )
    connection.commit()
    yield
    connection.execute(
        text("SELECT pg_advisory_unlock(:id)"), {"id": MIGRATION_LOCK_ID}
    )
    connection.commit()
