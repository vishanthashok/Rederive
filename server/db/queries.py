"""SQL for the record DAG. Every function takes an open psycopg connection."""

from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

Conn = psycopg.Connection

# Walk from the given versions of a record to every descendant that is the
# latest version of its record. A node reachable by paths of different
# lengths keeps its longest path, so ordering by depth is a topological order.
DESCENDANTS_SQL = """
WITH RECURSIVE walk(id, version, depth) AS (
    SELECT e.child_id, e.child_version, 1
    FROM edge e
    JOIN record_head h ON h.id = e.child_id AND h.latest_version = e.child_version
    WHERE e.parent_id = %(id)s AND e.parent_version = ANY(%(versions)s)
  UNION
    SELECT e.child_id, e.child_version, w.depth + 1
    FROM walk w
    JOIN edge e ON e.parent_id = w.id AND e.parent_version = w.version
    JOIN record_head h ON h.id = e.child_id AND h.latest_version = e.child_version
    WHERE w.depth < %(max_depth)s
)
SELECT id, version, max(depth) AS depth
FROM walk
GROUP BY id, version
ORDER BY depth, id
"""

# Every edge above a record version, with its distance from the start.
LINEAGE_SQL = """
WITH RECURSIVE anc(child_id, child_version, parent_id, parent_version, alias, depth) AS (
    SELECT e.child_id, e.child_version, e.parent_id, e.parent_version, e.alias, 1
    FROM edge e
    WHERE e.child_id = %(id)s AND e.child_version = %(version)s
  UNION
    SELECT e.child_id, e.child_version, e.parent_id, e.parent_version, e.alias, a.depth + 1
    FROM anc a
    JOIN edge e ON e.child_id = a.parent_id AND e.child_version = a.parent_version
    WHERE a.depth < %(max_depth)s
)
SELECT child_id, child_version, parent_id, parent_version, alias, min(depth) AS depth
FROM anc
GROUP BY child_id, child_version, parent_id, parent_version, alias
ORDER BY depth
"""

# Is `target` an ancestor of any of the given record ids (any version)?
IS_ANCESTOR_SQL = """
WITH RECURSIVE anc(id) AS (
    SELECT DISTINCT e.parent_id FROM edge e WHERE e.child_id = ANY(%(ids)s)
  UNION
    SELECT e.parent_id FROM anc a JOIN edge e ON e.child_id = a.id
)
SELECT EXISTS (SELECT 1 FROM anc WHERE id = %(target)s) AS found
"""

MAX_DEPTH = 1000


def descendants(conn: Conn, record_id: UUID, versions: list[int]) -> list[dict]:
    return conn.execute(
        DESCENDANTS_SQL, {"id": record_id, "versions": versions, "max_depth": MAX_DEPTH}
    ).fetchall()


def lineage_edges(conn: Conn, record_id: UUID, version: int) -> list[dict]:
    return conn.execute(
        LINEAGE_SQL, {"id": record_id, "version": version, "max_depth": MAX_DEPTH}
    ).fetchall()


def is_ancestor(conn: Conn, target: UUID, of_ids: list[UUID]) -> bool:
    return conn.execute(IS_ANCESTOR_SQL, {"ids": of_ids, "target": target}).fetchone()["found"]


def upsert_recipe(conn: Conn, h: str, template: str, model: str, params: dict) -> None:
    conn.execute(
        "INSERT INTO recipe (hash, template, model, params) VALUES (%s, %s, %s, %s) "
        "ON CONFLICT (hash) DO NOTHING",
        (h, template, model, Jsonb(params)),
    )


def get_recipe(conn: Conn, h: str) -> dict | None:
    return conn.execute("SELECT * FROM recipe WHERE hash = %s", (h,)).fetchone()


def insert_record(
    conn: Conn,
    record_id: UUID,
    version: int,
    kind: str,
    text: str,
    embedding: list[float] | None,
    recipe_hash: str | None,
    content_version: int,
    meta: dict[str, Any],
    status: str = "valid",
) -> None:
    conn.execute(
        "INSERT INTO record (id, version, kind, text, embedding, status, recipe_hash, "
        "content_version, meta) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (record_id, version, kind, text, embedding, status, recipe_hash, content_version, Jsonb(meta)),
    )


def insert_edges(
    conn: Conn, child_id: UUID, child_version: int, parents: list[tuple[UUID, int, int]],
    alias: bool = False,
) -> None:
    """parents: (parent_id, parent_version, position)."""
    for parent_id, parent_version, position in parents:
        conn.execute(
            "INSERT INTO edge (child_id, child_version, parent_id, parent_version, alias, position) "
            "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
            (child_id, child_version, parent_id, parent_version, alias, position),
        )


def get_head(conn: Conn, record_id: UUID, lock: bool = False) -> dict | None:
    sql = "SELECT * FROM record_head WHERE id = %s" + (" FOR UPDATE" if lock else "")
    return conn.execute(sql, (record_id,)).fetchone()


def get_record(conn: Conn, record_id: UUID, version: int | None = None) -> dict | None:
    if version is None:
        return conn.execute(
            "SELECT r.* FROM record r JOIN record_head h ON h.id = r.id AND h.latest_version = r.version "
            "WHERE r.id = %s",
            (record_id,),
        ).fetchone()
    return conn.execute(
        "SELECT * FROM record WHERE id = %s AND version = %s", (record_id, version)
    ).fetchone()


def get_versions(conn: Conn, record_id: UUID) -> list[dict]:
    return conn.execute(
        "SELECT version, status, content_version, deleted, created_at, recipe_hash "
        "FROM record WHERE id = %s ORDER BY version",
        (record_id,),
    ).fetchall()


def set_status(conn: Conn, record_id: UUID, version: int, status: str) -> None:
    conn.execute(
        "UPDATE record SET status = %s WHERE id = %s AND version = %s", (status, record_id, version)
    )


def bump_fence(conn: Conn, record_id: UUID) -> int:
    return conn.execute(
        "UPDATE record_head SET fence_token = fence_token + 1 WHERE id = %s RETURNING fence_token",
        (record_id,),
    ).fetchone()["fence_token"]


def parent_edges(conn: Conn, record_id: UUID, version: int) -> list[dict]:
    """The newest parent version per parent id for one child version, in input order."""
    return conn.execute(
        "SELECT * FROM ("
        "  SELECT DISTINCT ON (parent_id) parent_id, parent_version, alias, position "
        "  FROM edge WHERE child_id = %s AND child_version = %s "
        "  ORDER BY parent_id, parent_version DESC"
        ") p ORDER BY position, parent_id",
        (record_id, version),
    ).fetchall()


def active_constraints(conn: Conn) -> list[dict]:
    return conn.execute(
        "SELECT id, kind, payload, source_id FROM constraint_rule WHERE kind = 'must_not_contain'"
    ).fetchall()


def insert_verifications(conn: Conn, record_id: UUID, version: int, results, attempt: int) -> None:
    for r in results:
        conn.execute(
            "INSERT INTO verification (record_id, version, constraint_id, exact_hit, "
            "normalized_hit, paraphrase_hit, attempt) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (record_id, version, r.constraint_id, r.exact_hit, r.normalized_hit, r.paraphrase_hit, attempt),
        )


def graph(conn: Conn, user: str | None = None) -> dict:
    where = "WHERE r.meta->>'user' = %(user)s" if user else ""
    nodes = conn.execute(
        "SELECT r.id, r.version, r.kind, r.status, r.deleted, r.meta, r.content_version, "
        "CASE WHEN r.deleted THEN '[deleted]' ELSE r.text END AS text "
        "FROM record r JOIN record_head h ON h.id = r.id AND h.latest_version = r.version "
        f"{where} ORDER BY r.created_at",
        {"user": user},
    ).fetchall()
    edges = conn.execute(
        "SELECT DISTINCT ON (e.child_id, e.parent_id) e.child_id, e.parent_id, e.parent_version, e.alias "
        "FROM edge e JOIN record_head h ON h.id = e.child_id AND h.latest_version = e.child_version "
        "ORDER BY e.child_id, e.parent_id, e.parent_version DESC"
    ).fetchall()
    ids = {n["id"] for n in nodes}
    edges = [e for e in edges if e["child_id"] in ids and e["parent_id"] in ids]
    return {"nodes": nodes, "edges": edges}


EXPOSURE_SQL = """
SELECT x.tool_call_id, x.tool_name, x.at, x.record_id, x.version,
       r.kind, r.status AS read_status, r.deleted,
       CASE WHEN r.deleted THEN '[deleted]' ELSE r.text END AS read_text,
       l.version AS latest_version, l.status AS latest_status,
       CASE WHEN l.deleted THEN '[deleted]' ELSE l.text END AS latest_text,
       CASE
         WHEN l.status = 'valid' AND l.content_version = r.content_version THEN 'valid'
         WHEN l.status IN ('stale', 'rebuilding') AND l.content_version = r.content_version
              AND r.status NOT IN ('retracted') THEN 'pending'
         ELSE 'invalid'
       END AS state
FROM exposure x
JOIN record r ON r.id = x.record_id AND r.version = x.version
JOIN record_head h ON h.id = x.record_id
JOIN record l ON l.id = h.id AND l.version = h.latest_version
ORDER BY x.at DESC, x.tool_call_id
"""


def exposures(conn: Conn, stale_only: bool) -> list[dict]:
    rows = conn.execute(EXPOSURE_SQL).fetchall()
    return [r for r in rows if r["state"] != "valid"] if stale_only else rows
