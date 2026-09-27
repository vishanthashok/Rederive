"""Connection pool and schema bootstrap."""

from pathlib import Path

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from server.config import settings

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

_pool: ConnectionPool | None = None


def get_pool(database_url: str | None = None) -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            database_url or settings.database_url,
            min_size=1,
            max_size=10,
            kwargs={"row_factory": dict_row, "autocommit": True},
            open=True,
        )
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def apply_schema(pool: ConnectionPool) -> None:
    with pool.connection() as conn:
        # Serialize concurrent bootstraps from server and worker.
        conn.execute("SELECT pg_advisory_lock(424242)")
        try:
            conn.execute(SCHEMA_PATH.read_text())
        finally:
            conn.execute("SELECT pg_advisory_unlock(424242)")


TABLES = [
    "verification",
    "event",
    "rebuild_job",
    "exposure",
    "constraint_rule",
    "edge",
    "record_head",
    "record",
    "recipe",
]


def reset(pool: ConnectionPool) -> None:
    with pool.connection() as conn:
        conn.execute(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE")
