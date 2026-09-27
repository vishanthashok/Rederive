"""Retraction walk: mark descendants stale and create rebuild jobs."""

from dataclasses import dataclass, field
from uuid import UUID

from server.db import queries as q
from server.events import emit

LIVE = ("valid", "stale", "rebuilding")


@dataclass
class Invalidation:
    stale: list[dict] = field(default_factory=list)  # {id, version, depth}
    jobs: list[tuple[int, int]] = field(default_factory=list)  # (job_id, depth)

    @property
    def stale_count(self) -> int:
        return len(self.stale)

    @property
    def job_ids(self) -> list[int]:
        return [j for j, _ in self.jobs]


def invalidate(conn, record_id: UUID, versions: list[int], cause: str) -> Invalidation:
    """Mark every live descendant of the given versions stale.

    Runs inside the caller's transaction. Each stale record gets a new fence
    token, which also voids any queued or running job for it. The caller
    enqueues the returned jobs after commit.
    """
    result = Invalidation()
    for row in q.descendants(conn, record_id, versions):
        rec = q.get_record(conn, row["id"], row["version"])
        if rec is None or rec["status"] not in LIVE:
            continue
        q.set_status(conn, row["id"], row["version"], "stale")
        fence = q.bump_fence(conn, row["id"])
        conn.execute(
            "UPDATE rebuild_job SET state = 'discarded', finished_at = now(), "
            "result = result || '{\"reason\": \"superseded_by_newer_job\"}'::jsonb "
            "WHERE record_id = %s AND state = 'queued'",
            (row["id"],),
        )
        job_id = conn.execute(
            "INSERT INTO rebuild_job (record_id, target_version, fence_token, depth) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (row["id"], row["version"] + 1, fence, row["depth"]),
        ).fetchone()["id"]
        result.stale.append({"id": row["id"], "version": row["version"], "depth": row["depth"]})
        result.jobs.append((job_id, row["depth"]))
        emit(conn, "stale", record_id=row["id"], version=row["version"], depth=row["depth"],
             job_id=job_id, cause=cause)
    return result
