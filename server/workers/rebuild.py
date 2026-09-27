"""Rebuild worker: recompute stale records in topological order.

A job carries the fence token its record had when it was invalidated. The
worker writes a new version only if that token is still current. A newer
retraction bumps the token, so a slow worker's output is discarded.

Run with: python -m server.workers.rebuild
"""

import logging
import time
from uuid import UUID

from psycopg.types.json import Jsonb

from server import cutoff
from server.config import settings
from server.db import queries as q
from server.db.pool import apply_schema, get_pool
from server.embed import Embedder, get_embedder
from server.events import emit
from server.llm import LLMProvider, get_llm
from server.memory import generate

log = logging.getLogger("rederive.worker")

WAIT = "wait"
PENDING = ("stale", "rebuilding")


def _finish(conn, job_id: int, state: str, **result) -> str:
    conn.execute(
        "UPDATE rebuild_job SET state = %s, finished_at = now(), result = result || %s WHERE id = %s",
        (state, Jsonb({k: (str(v) if isinstance(v, UUID) else v) for k, v in result.items()}), job_id),
    )
    return state


def _has_active_job(conn, record_id: UUID) -> bool:
    return conn.execute(
        "SELECT EXISTS (SELECT 1 FROM rebuild_job WHERE record_id = %s "
        "AND state IN ('queued', 'running')) AS x",
        (record_id,),
    ).fetchone()["x"]


def process_job(conn, job_id: int, llm: LLMProvider, embedder: Embedder) -> str:
    """Process one job. Returns the final job state, 'wait', or 'noop'."""
    # Phase 1: claim the job and snapshot inputs.
    with conn.transaction():
        job = conn.execute("SELECT * FROM rebuild_job WHERE id = %s FOR UPDATE", (job_id,)).fetchone()
        if job is None or job["state"] != "queued":
            return "noop"
        rid = job["record_id"]
        head = q.get_head(conn, rid)
        if head["fence_token"] != job["fence_token"]:
            return _finish(conn, job_id, "discarded", reason="fence_token_advanced")
        cur = q.get_record(conn, rid, head["latest_version"])
        if cur["status"] not in PENDING:
            return _finish(conn, job_id, "discarded", reason=f"record_is_{cur['status']}")

        plan = []
        for e in q.parent_edges(conn, rid, cur["version"]):
            used = q.get_record(conn, e["parent_id"], e["parent_version"])
            latest = q.get_record(conn, e["parent_id"])
            if latest["status"] in PENDING:
                if _has_active_job(conn, latest["id"]):
                    return WAIT
                q.set_status(conn, rid, cur["version"], "stale")
                emit(conn, "failed", record_id=rid, job_id=job_id, reason="parent_failed")
                return _finish(conn, job_id, "failed", reason="parent_failed", parent_id=latest["id"])
            plan.append((used, latest, e["position"]))

        conn.execute("UPDATE rebuild_job SET state = 'running' WHERE id = %s", (job_id,))
        q.set_status(conn, rid, cur["version"], "rebuilding")
        emit(conn, "rebuilding", record_id=rid, version=cur["version"], job_id=job_id)
        recipe = q.get_recipe(conn, cur["recipe_hash"])

    live = [p for p in plan if p[1]["status"] == "valid" and not p[1]["deleted"]]
    dropped = [str(used["id"]) for used, latest, _ in plan if latest["status"] != "valid" or latest["deleted"]]
    unchanged = len(live) == len(plan) and all(
        used["content_version"] == latest["content_version"] for used, latest, _ in live
    )

    # Phase 2: no input changed in content. Point at the new parent versions.
    if unchanged:
        with conn.transaction():
            if not _fence_ok(conn, job):
                return _finish(conn, job_id, "discarded", reason="fence_token_advanced")
            q.set_status(conn, rid, cur["version"], "valid")
            q.insert_edges(
                conn, rid, cur["version"],
                [(l["id"], l["version"], pos) for u, l, pos in live if l["version"] != u["version"]],
                alias=True,
            )
            emit(conn, "skipped", record_id=rid, version=cur["version"], job_id=job_id)
            return _finish(conn, job_id, "skipped", reason="inputs_equivalent")

    # Phase 2: every input is gone, so the record has no support left.
    if not live:
        with conn.transaction():
            if not _fence_ok(conn, job):
                return _finish(conn, job_id, "discarded", reason="fence_token_advanced")
            q.set_status(conn, rid, cur["version"], "retracted")
            emit(conn, "retracted", record_id=rid, versions=[cur["version"]], cause="no_inputs")
            return _finish(conn, job_id, "done", reason="no_inputs", retracted=True)

    # Phase 2: run the recipe outside any transaction.
    gen = generate(conn, recipe, [latest["text"] for _, latest, _ in live], llm, embedder)
    decision = None if gen.violated else cutoff.decide(
        cur["text"], gen.text, cur["embedding"], gen.embedding, llm
    )

    with conn.transaction():
        head = q.get_head(conn, rid, lock=True)
        if head["fence_token"] != job["fence_token"]:
            return _finish(conn, job_id, "discarded", reason="fence_token_advanced")
        if gen.violated:
            q.set_status(conn, rid, cur["version"], "stale")
            emit(conn, "failed", record_id=rid, job_id=job_id, reason="deletion_verifier")
            log.error("rebuild of %s still leaks deleted content after exclusion retry", rid)
            return _finish(conn, job_id, "failed", reason="deletion_verifier", verification=gen.report())

        version = head["latest_version"] + 1
        content_version = cur["content_version"] if decision.equal else version
        q.insert_record(conn, rid, version, cur["kind"], gen.text, gen.embedding, cur["recipe_hash"],
                        content_version, cur["meta"])
        q.insert_edges(conn, rid, version, [(l["id"], l["version"], pos) for _, l, pos in live])
        for attempt, results in gen.attempts:
            q.insert_verifications(conn, rid, version, results, attempt)
        q.set_status(conn, rid, cur["version"], "equivalent" if decision.equal else "superseded")
        conn.execute("UPDATE record_head SET latest_version = %s WHERE id = %s", (version, rid))
        state = "cut_off" if decision.equal else "done"
        emit(conn, "cut_off" if decision.equal else "rebuilt", record_id=rid, version=version,
             job_id=job_id, similarity=round(decision.similarity, 4), method=decision.method)
        return _finish(
            conn, job_id, state, new_version=version, similarity=round(decision.similarity, 4),
            method=decision.method, dropped_inputs=dropped, verification=gen.report(),
        )


def _fence_ok(conn, job: dict) -> bool:
    return q.get_head(conn, job["record_id"], lock=True)["fence_token"] == job["fence_token"]


def drain(pool, llm: LLMProvider | None = None, embedder: Embedder | None = None,
          max_passes: int = 1000) -> dict[str, int]:
    """Process queued jobs straight from Postgres until none are left.

    Used by tests and by the worker when Redis is unavailable.
    """
    llm, embedder = llm or get_llm(), embedder or get_embedder()
    counts: dict[str, int] = {}
    with pool.connection() as conn:
        for _ in range(max_passes):
            jobs = conn.execute(
                "SELECT id FROM rebuild_job WHERE state = 'queued' ORDER BY depth, id"
            ).fetchall()
            if not jobs:
                return counts
            progressed = False
            for job in jobs:
                outcome = process_job(conn, job["id"], llm, embedder)
                if outcome != WAIT:
                    progressed = True
                    counts[outcome] = counts.get(outcome, 0) + 1
            if not progressed:
                raise RuntimeError("rebuild queue is stuck: every job is waiting")
    raise RuntimeError("drain did not finish")


def sweep(conn, queue) -> None:
    """Recover jobs lost from Redis or left running by a dead worker."""
    stuck = conn.execute(
        "UPDATE rebuild_job SET state = 'queued' WHERE state = 'running' "
        "AND created_at < now() - interval '5 minutes' RETURNING id, record_id"
    ).fetchall()
    for row in stuck:
        conn.execute(
            "UPDATE record r SET status = 'stale' FROM record_head h "
            "WHERE r.id = %s AND h.id = r.id AND r.version = h.latest_version AND r.status = 'rebuilding'",
            (row["record_id"],),
        )
    queued = conn.execute("SELECT id, depth FROM rebuild_job WHERE state = 'queued'").fetchall()
    queue.push([(r["id"], r["depth"]) for r in queued])


def run_worker() -> None:
    from server.workers.queue import RedisQueue

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    pool = get_pool()
    apply_schema(pool)
    queue = RedisQueue(settings.redis_url)
    llm, embedder = get_llm(), get_embedder()
    log.info("worker started (llm=%s, embedder=%s)", settings.llm, settings.embedder)
    last_sweep = 0.0
    while True:
        if time.monotonic() - last_sweep > 5:
            with pool.connection() as conn:
                sweep(conn, queue)
            last_sweep = time.monotonic()
        item = queue.pop(timeout=1.0)
        if item is None:
            continue
        job_id, depth = item
        try:
            with pool.connection() as conn:
                outcome = process_job(conn, job_id, llm, embedder)
        except Exception:
            log.exception("job %s crashed", job_id)
            with pool.connection() as conn:
                conn.execute(
                    "UPDATE rebuild_job SET state = 'failed', finished_at = now(), "
                    "result = result || '{\"reason\": \"exception\"}'::jsonb WHERE id = %s AND state = 'running'",
                    (job_id,),
                )
                conn.execute(
                    "UPDATE record r SET status = 'stale' FROM rebuild_job j, record_head h "
                    "WHERE j.id = %s AND r.id = j.record_id AND h.id = r.id "
                    "AND r.version = h.latest_version AND r.status = 'rebuilding'",
                    (job_id,),
                )
            continue
        if outcome == WAIT:
            # A parent is still rebuilding on another worker. Back off briefly.
            time.sleep(0.05)
            queue.push([(job_id, depth)])
        else:
            log.info("job %s -> %s", job_id, outcome)


if __name__ == "__main__":
    run_worker()
