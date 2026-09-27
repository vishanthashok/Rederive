"""Event log plus LISTEN/NOTIFY fan-out for the UI."""

import json
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

CHANNEL = "rederive_events"


def emit(conn, kind: str, **payload: Any) -> None:
    """Record an event. The NOTIFY is delivered when the transaction commits."""
    payload = {k: (str(v) if isinstance(v, UUID) else v) for k, v in payload.items()}
    row = conn.execute(
        "INSERT INTO event (kind, payload) VALUES (%s, %s) RETURNING id, at",
        (kind, Jsonb(payload)),
    ).fetchone()
    message = {"id": row["id"], "kind": kind, "at": row["at"].isoformat(), **payload}
    conn.execute("SELECT pg_notify(%s, %s)", (CHANNEL, json.dumps(message, default=str)))
