"""SQLite storage for the record DAG.

A port of server/db/schema.sql and server/db/queries.py. Record versions are
immutable: a rebuild or correction inserts a new version and flips the
status of the old one. One process owns a connection. Several processes
(two chat sessions) can share the file: writes run in BEGIN IMMEDIATE
transactions and fence tokens reject rebuilds that raced a newer change.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS recipe (
  hash      TEXT PRIMARY KEY,
  template  TEXT NOT NULL,
  model     TEXT NOT NULL,
  params    TEXT NOT NULL DEFAULT '{}'
);

-- status: valid | stale | retracted | superseded | equivalent
-- superseded: replaced by a version with different content.
-- equivalent: replaced by a version the cutoff judged equal. Versions judged
-- equal share a content_version, so children built on either need no rebuild.
CREATE TABLE IF NOT EXISTS record (
  id              TEXT NOT NULL,
  version         INTEGER NOT NULL,
  kind            TEXT NOT NULL,
  text            TEXT NOT NULL,
  embedding       TEXT,
  status          TEXT NOT NULL DEFAULT 'valid',
  recipe_hash     TEXT REFERENCES recipe(hash),
  content_version INTEGER NOT NULL,
  meta            TEXT NOT NULL DEFAULT '{}',
  deleted         INTEGER NOT NULL DEFAULT 0,
  created_at      TEXT NOT NULL,
  PRIMARY KEY (id, version)
);

-- fence_token increments on every invalidation, so a rebuild submitted
-- against an older token is rejected.
CREATE TABLE IF NOT EXISTS record_head (
  id              TEXT PRIMARY KEY,
  latest_version  INTEGER NOT NULL,
  fence_token     INTEGER NOT NULL DEFAULT 0
);

-- alias edges point a child at a newer, equivalent parent version without
-- rebuilding the child. position keeps the input order from derive time.
CREATE TABLE IF NOT EXISTS edge (
  child_id        TEXT NOT NULL,
  child_version   INTEGER NOT NULL,
  parent_id       TEXT NOT NULL,
  parent_version  INTEGER NOT NULL,
  alias           INTEGER NOT NULL DEFAULT 0,
  position        INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (child_id, child_version, parent_id, parent_version)
);
CREATE INDEX IF NOT EXISTS edge_parent_idx ON edge (parent_id, parent_version);

CREATE TABLE IF NOT EXISTS constraint_rule (
  id         TEXT PRIMARY KEY,
  kind       TEXT NOT NULL,
  payload    TEXT NOT NULL,
  source_id  TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS exposure (
  call_id    TEXT NOT NULL,
  tool_name  TEXT,
  record_id  TEXT NOT NULL,
  version    INTEGER NOT NULL,
  at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS exposure_record_idx ON exposure (record_id, version);

-- state: queued | done | cut_off | skipped | discarded | failed
CREATE TABLE IF NOT EXISTS rebuild_job (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  record_id       TEXT NOT NULL,
  target_version  INTEGER NOT NULL,
  state           TEXT NOT NULL DEFAULT 'queued',
  fence_token     INTEGER NOT NULL,
  depth           INTEGER NOT NULL,
  cause           TEXT,
  result          TEXT NOT NULL DEFAULT '{}',
  created_at      TEXT NOT NULL,
  finished_at     TEXT
);
CREATE INDEX IF NOT EXISTS rebuild_job_state_idx ON rebuild_job (state);
"""

# Walk from the given versions of a record to every descendant that is the
# latest version of its record. A node reachable by paths of different
# lengths keeps its longest path, so ordering by depth is a topological order.
DESCENDANTS_SQL = """
WITH RECURSIVE walk(id, version, depth) AS (
    SELECT e.child_id, e.child_version, 1
    FROM edge e
    JOIN record_head h ON h.id = e.child_id AND h.latest_version = e.child_version
    WHERE e.parent_id = ? AND e.parent_version IN ({versions})
  UNION
    SELECT e.child_id, e.child_version, w.depth + 1
    FROM walk w
    JOIN edge e ON e.parent_id = w.id AND e.parent_version = w.version
    JOIN record_head h ON h.id = e.child_id AND h.latest_version = e.child_version
    WHERE w.depth < 1000
)
SELECT id, version, max(depth) AS depth FROM walk GROUP BY id, version ORDER BY depth, id
"""

ANCESTORS_SQL = """
WITH RECURSIVE anc(id) AS (
    SELECT DISTINCT parent_id FROM edge WHERE child_id IN ({ids})
  UNION
    SELECT e.parent_id FROM anc a JOIN edge e ON e.child_id = a.id
)
SELECT EXISTS (SELECT 1 FROM anc WHERE id = ?) AS found
"""

JSON_COLUMNS = ("meta", "params", "result", "embedding")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def default_path() -> Path:
    return Path.home() / ".rederive" / "memory.db"


def _row(cursor: sqlite3.Cursor, row: tuple) -> dict:
    out = {}
    for (name, *_), value in zip(cursor.description, row):
        if name in JSON_COLUMNS and isinstance(value, str):
            value = json.loads(value)
        elif name in ("deleted", "alias"):
            value = bool(value)
        out[name] = value
    return out


class Store:
    def __init__(self, path: str | Path | None = None):
        path = Path(path) if path is not None else default_path()
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        # isolation_level=None: autocommit, and transactions are explicit.
        self.conn = sqlite3.connect(str(path), isolation_level=None, timeout=30)
        self.conn.row_factory = _row
        self.conn.execute("PRAGMA foreign_keys = ON")
        if str(path) != ":memory:":
            self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.executescript(SCHEMA)
        self._depth = 0

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """BEGIN IMMEDIATE, or a savepoint when already inside one."""
        if self._depth:
            self._depth += 1
            try:
                yield
            finally:
                self._depth -= 1
            return
        self.conn.execute("BEGIN IMMEDIATE")
        self._depth = 1
        try:
            yield
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        else:
            self.conn.execute("COMMIT")
        finally:
            self._depth = 0

    def execute(self, sql: str, params: tuple | list = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, params)

    def one(self, sql: str, params: tuple | list = ()) -> dict | None:
        return self.conn.execute(sql, params).fetchone()

    def all(self, sql: str, params: tuple | list = ()) -> list[dict]:
        return self.conn.execute(sql, params).fetchall()

    # -- recipes ------------------------------------------------------------

    def upsert_recipe(self, h: str, template: str, model: str, params: dict) -> None:
        self.execute(
            "INSERT OR IGNORE INTO recipe (hash, template, model, params) VALUES (?, ?, ?, ?)",
            (h, template, model, json.dumps(params)),
        )

    def get_recipe(self, h: str | None) -> dict | None:
        return self.one("SELECT * FROM recipe WHERE hash = ?", (h,)) if h else None

    # -- records ------------------------------------------------------------

    def insert_record(
        self, record_id: str, version: int, kind: str, text: str, embedding: list[float] | None,
        recipe_hash: str | None, content_version: int, meta: dict[str, Any], status: str = "valid",
    ) -> None:
        self.execute(
            "INSERT INTO record (id, version, kind, text, embedding, status, recipe_hash, "
            "content_version, meta, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (record_id, version, kind, text, json.dumps(embedding) if embedding else None, status,
             recipe_hash, content_version, json.dumps(meta), now()),
        )

    def get_record(self, record_id: str, version: int | None = None) -> dict | None:
        if version is None:
            return self.one(
                "SELECT r.* FROM record r JOIN record_head h "
                "ON h.id = r.id AND h.latest_version = r.version WHERE r.id = ?",
                (record_id,),
            )
        return self.one("SELECT * FROM record WHERE id = ? AND version = ?", (record_id, version))

    def latest_records(self) -> list[dict]:
        return self.all(
            "SELECT r.* FROM record r JOIN record_head h "
            "ON h.id = r.id AND h.latest_version = r.version ORDER BY r.created_at, r.id"
        )

    def get_versions(self, record_id: str) -> list[dict]:
        return self.all(
            "SELECT version, status, content_version, deleted, created_at, recipe_hash, text "
            "FROM record WHERE id = ? ORDER BY version",
            (record_id,),
        )

    def set_status(self, record_id: str, version: int, status: str) -> None:
        self.execute("UPDATE record SET status = ? WHERE id = ? AND version = ?",
                     (status, record_id, version))

    # -- heads --------------------------------------------------------------

    def insert_head(self, record_id: str) -> None:
        self.execute("INSERT INTO record_head (id, latest_version) VALUES (?, 1)", (record_id,))

    def get_head(self, record_id: str) -> dict | None:
        return self.one("SELECT * FROM record_head WHERE id = ?", (record_id,))

    def set_latest(self, record_id: str, version: int) -> None:
        self.execute("UPDATE record_head SET latest_version = ? WHERE id = ?", (version, record_id))

    def bump_fence(self, record_id: str) -> int:
        self.execute("UPDATE record_head SET fence_token = fence_token + 1 WHERE id = ?", (record_id,))
        return self.get_head(record_id)["fence_token"]

    # -- edges --------------------------------------------------------------

    def insert_edges(self, child_id: str, child_version: int,
                     parents: list[tuple[str, int, int]], alias: bool = False) -> None:
        """parents: (parent_id, parent_version, position)."""
        for parent_id, parent_version, position in parents:
            self.execute(
                "INSERT OR IGNORE INTO edge (child_id, child_version, parent_id, parent_version, "
                "alias, position) VALUES (?, ?, ?, ?, ?, ?)",
                (child_id, child_version, parent_id, parent_version, int(alias), position),
            )

    def parent_edges(self, record_id: str, version: int) -> list[dict]:
        """The newest parent version per parent id for one child version, in input order."""
        rows = self.all(
            "SELECT parent_id, parent_version, alias, position FROM edge "
            "WHERE child_id = ? AND child_version = ? ORDER BY parent_id, parent_version DESC",
            (record_id, version),
        )
        newest: dict[str, dict] = {}
        for r in rows:
            newest.setdefault(r["parent_id"], r)
        return sorted(newest.values(), key=lambda r: (r["position"], r["parent_id"]))

    def descendants(self, record_id: str, versions: list[int]) -> list[dict]:
        if not versions:
            return []
        marks = ",".join("?" * len(versions))
        return self.all(DESCENDANTS_SQL.format(versions=marks), (record_id, *versions))

    def is_ancestor(self, target: str, of_ids: list[str]) -> bool:
        if not of_ids:
            return False
        marks = ",".join("?" * len(of_ids))
        return bool(self.one(ANCESTORS_SQL.format(ids=marks), (*of_ids, target))["found"])

    # -- constraints --------------------------------------------------------

    def active_constraints(self) -> list[dict]:
        return self.all("SELECT id, kind, payload, source_id FROM constraint_rule "
                        "WHERE kind = 'must_not_contain'")

    # -- jobs ---------------------------------------------------------------

    def queued_jobs(self) -> list[dict]:
        return self.all("SELECT * FROM rebuild_job WHERE state = 'queued' ORDER BY depth, id")

    def finish_job(self, job_id: int, state: str, **result: Any) -> str:
        job = self.one("SELECT result FROM rebuild_job WHERE id = ?", (job_id,))
        merged = {**(job["result"] if job else {}), **result}
        self.execute(
            "UPDATE rebuild_job SET state = ?, finished_at = ?, result = ? WHERE id = ?",
            (state, now(), json.dumps(merged), job_id),
        )
        return state
