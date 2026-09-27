"""Memory operations: observe, derive, retract, correct, delete, read.

Each function takes an autocommit connection, opens its own transaction, and
calls `enqueue(jobs)` only after commit so workers never see uncommitted jobs.
"""

from dataclasses import dataclass, field
from typing import Callable
from uuid import UUID, uuid4

from rederive.recipes import recipe_hash
from server import verify
from server.config import settings
from server.db import queries as q
from server.embed import Embedder
from server.events import emit
from server.invalidate import Invalidation, invalidate
from server.llm import LLMProvider, normalize, sensitive_spans

Enqueue = Callable[[list[tuple[int, int]]], None]


def _no_enqueue(jobs: list[tuple[int, int]]) -> None:
    pass


class MemoryError_(Exception):
    status = 400


class NotFound(MemoryError_):
    status = 404


class Conflict(MemoryError_):
    status = 409


class Gone(MemoryError_):
    status = 410


class Unprocessable(MemoryError_):
    status = 422


KINDS = {"observation", "summary", "belief", "procedure", "reflection"}


@dataclass
class Generated:
    text: str
    embedding: list[float]
    attempts: list[tuple[int, list[verify.CheckResult]]] = field(default_factory=list)

    @property
    def violated(self) -> bool:
        return bool(verify.violations(self.attempts[-1][1])) if self.attempts else False

    def report(self) -> list[dict]:
        return [
            {"attempt": n, "checks": [r.to_json() for r in results]} for n, results in self.attempts
        ]


def generate(
    conn, recipe: dict, inputs: list[str], llm: LLMProvider, embedder: Embedder
) -> Generated:
    """Run a recipe, verify it against deletion constraints, retry once with an
    explicit exclusion instruction if the first output leaks deleted content."""
    constraints = q.active_constraints(conn)
    args = (recipe["template"], recipe["model"], recipe["params"] or {}, inputs)
    text = llm.run_recipe(*args, exclusions=[])
    results = verify.check(text, constraints, llm)
    attempts = [(1, results)]
    leaked = verify.violations(results)
    if leaked:
        text = llm.run_recipe(*args, exclusions=[r.payload for r in leaked])
        attempts.append((2, verify.check(text, constraints, llm)))
    return Generated(text, embedder.embed(text), attempts)


def record_json(rec: dict, include_embedding: bool = False) -> dict:
    out = {k: v for k, v in rec.items() if k != "embedding" or include_embedding}
    if rec.get("deleted"):
        out["text"] = "[deleted]"
    return out


# --------------------------------------------------------------------------
# observe / read


def observe(conn, text: str, meta: dict | None, embedder: Embedder, kind: str = "observation") -> dict:
    record_id = uuid4()
    with conn.transaction():
        q.insert_record(conn, record_id, 1, kind, text, embedder.embed(text), None, 1, meta or {})
        conn.execute("INSERT INTO record_head (id, latest_version) VALUES (%s, 1)", (record_id,))
        emit(conn, "observed", record_id=record_id, version=1)
    return {"id": record_id, "version": 1}


def read(
    conn,
    record_id: UUID,
    version: int | None = None,
    tool_call_id: str | None = None,
    tool_name: str | None = None,
) -> dict:
    rec = q.get_record(conn, record_id, version)
    if rec is None:
        raise NotFound(f"record {record_id} not found")
    if rec["deleted"]:
        raise Gone(f"record {record_id} was deleted")
    if tool_call_id:
        conn.execute(
            "INSERT INTO exposure (tool_call_id, tool_name, record_id, version) VALUES (%s, %s, %s, %s)",
            (tool_call_id, tool_name, rec["id"], rec["version"]),
        )
    return record_json(rec)


# --------------------------------------------------------------------------
# derive


def parse_input(ref: str | dict) -> tuple[UUID, int | None]:
    if isinstance(ref, dict):
        return UUID(str(ref["id"])), ref.get("version")
    if "@" in ref:
        rid, ver = ref.split("@", 1)
        return UUID(rid), int(ver)
    return UUID(ref), None


def _resolve_inputs(conn, refs: list[str | dict]) -> list[dict]:
    out = []
    for ref in refs:
        rid, ver = parse_input(ref)
        rec = q.get_record(conn, rid, ver)
        if rec is None:
            raise NotFound(f"input {ref} not found")
        if rec["deleted"] or rec["status"] == "retracted":
            raise Gone(f"input {ref} is retracted")
        if rec["status"] != "valid":
            raise Conflict(f"input {ref} is {rec['status']}; wait for rebuild or pin a valid version")
        out.append(rec)
    return out


def derive(
    conn,
    inputs: list[str | dict],
    recipe: dict,
    kind: str,
    llm: LLMProvider,
    embedder: Embedder,
    meta: dict | None = None,
    target_id: UUID | None = None,
    fan_in_k: int | None = None,
    enqueue: Enqueue = _no_enqueue,
) -> dict:
    if kind not in KINDS - {"observation"}:
        raise MemoryError_(f"kind must be one of {sorted(KINDS - {'observation'})}")
    if not inputs:
        raise MemoryError_("derive needs at least one input")
    recipe = {"template": recipe["template"], "model": recipe.get("model", "default"),
              "params": recipe.get("params") or {}}
    rhash = recipe_hash(recipe["template"], recipe["model"], recipe["params"])
    with conn.transaction():
        q.upsert_recipe(conn, rhash, recipe["template"], recipe["model"], recipe["params"])
    parents = _resolve_inputs(conn, inputs)

    k = fan_in_k or int(recipe["params"].get("fan_in_k", settings.fan_in_k))
    if len(parents) > k and kind == "summary" and target_id is None:
        from server.fanin import build_tree

        return build_tree(conn, parents, recipe, rhash, kind, meta or {}, k, llm, embedder)
    return derive_one(conn, parents, recipe, rhash, kind, meta or {}, llm, embedder, target_id, enqueue)


def derive_one(
    conn,
    parents: list[dict],
    recipe: dict,
    rhash: str,
    kind: str,
    meta: dict,
    llm: LLMProvider,
    embedder: Embedder,
    target_id: UUID | None = None,
    enqueue: Enqueue = _no_enqueue,
) -> dict:
    parent_ids = [p["id"] for p in parents]
    if target_id is not None:
        # A new version of an existing record. Its own descendants must not be
        # inputs, or the graph would loop. Version it as a new record instead.
        if target_id in parent_ids:
            raise Conflict("cycle: a record cannot be derived from itself")
        if q.is_ancestor(conn, target_id, parent_ids):
            raise Conflict(f"cycle: an input depends on {target_id}")

    gen = generate(conn, recipe, [p["text"] for p in parents], llm, embedder)
    if gen.violated:
        raise Unprocessable(
            {"error": "output still contains deleted content after exclusion retry",
             "verification": gen.report()}
        )

    inv = Invalidation()
    with conn.transaction():
        if target_id is None:
            record_id, version = uuid4(), 1
            conn.execute("INSERT INTO record_head (id, latest_version) VALUES (%s, 1)", (record_id,))
        else:
            head = q.get_head(conn, target_id, lock=True)
            if head is None:
                raise NotFound(f"record {target_id} not found")
            old = q.get_record(conn, target_id, head["latest_version"])
            record_id, version = target_id, head["latest_version"] + 1
            conn.execute("UPDATE record_head SET latest_version = %s WHERE id = %s", (version, record_id))
            q.bump_fence(conn, record_id)
            if old["status"] != "retracted":
                q.set_status(conn, record_id, old["version"], "superseded")
        q.insert_record(conn, record_id, version, kind, gen.text, gen.embedding, rhash, version, meta)
        q.insert_edges(conn, record_id, version, [(p["id"], p["version"], i) for i, p in enumerate(parents)])
        for attempt, results in gen.attempts:
            q.insert_verifications(conn, record_id, version, results, attempt)
        if target_id is not None:
            inv = invalidate(conn, record_id, [version - 1], cause=f"new_version:{record_id}")
        emit(conn, "derived", record_id=record_id, version=version, record_kind=kind)
    enqueue(inv.jobs)
    return {"id": record_id, "version": version, "stale_count": inv.stale_count, "job_ids": inv.job_ids}


# --------------------------------------------------------------------------
# retract / correct / delete


def retract(conn, record_id: UUID, enqueue: Enqueue = _no_enqueue, cause: str = "retract") -> dict:
    with conn.transaction():
        head = q.get_head(conn, record_id, lock=True)
        if head is None:
            raise NotFound(f"record {record_id} not found")
        versions = [
            r["version"]
            for r in conn.execute(
                "UPDATE record SET status = 'retracted' WHERE id = %s AND status <> 'superseded' "
                "RETURNING version",
                (record_id,),
            ).fetchall()
        ]
        all_versions = [v["version"] for v in q.get_versions(conn, record_id)]
        q.bump_fence(conn, record_id)
        conn.execute(
            "UPDATE rebuild_job SET state = 'discarded', finished_at = now() "
            "WHERE record_id = %s AND state = 'queued'",
            (record_id,),
        )
        emit(conn, "retracted", record_id=record_id, versions=versions, cause=cause)
        inv = invalidate(conn, record_id, all_versions, cause=f"{cause}:{record_id}")
    enqueue(inv.jobs)
    return {"id": record_id, "stale_count": inv.stale_count, "job_ids": inv.job_ids,
            "stale": [{"id": s["id"], "version": s["version"], "depth": s["depth"]} for s in inv.stale]}


def correct(conn, record_id: UUID, text: str, embedder: Embedder, enqueue: Enqueue = _no_enqueue) -> dict:
    with conn.transaction():
        head = q.get_head(conn, record_id, lock=True)
        if head is None:
            raise NotFound(f"record {record_id} not found")
        old = q.get_record(conn, record_id, head["latest_version"])
        if old["deleted"]:
            raise Gone(f"record {record_id} was deleted")
        if old["kind"] != "observation":
            raise MemoryError_("only observations can be corrected; derived records rebuild from inputs")
        version = old["version"] + 1
        q.set_status(conn, record_id, old["version"], "superseded")
        q.insert_record(conn, record_id, version, old["kind"], text, embedder.embed(text), None,
                        version, old["meta"])
        conn.execute("UPDATE record_head SET latest_version = %s WHERE id = %s", (version, record_id))
        q.bump_fence(conn, record_id)
        emit(conn, "corrected", record_id=record_id, version=version)
        inv = invalidate(conn, record_id, [old["version"]], cause=f"correct:{record_id}")
    enqueue(inv.jobs)
    return {"id": record_id, "version": version, "stale_count": inv.stale_count, "job_ids": inv.job_ids}


def delete(conn, record_id: UUID, payload: str | None = None, enqueue: Enqueue = _no_enqueue) -> dict:
    rec = q.get_record(conn, record_id)
    if rec is None:
        raise NotFound(f"record {record_id} not found")
    if rec["deleted"]:
        raise Gone(f"record {record_id} was already deleted")
    payloads = [payload] if payload else [rec["text"], *sensitive_spans(rec["text"])]
    constraint_ids = []
    with conn.transaction():
        for p in dict.fromkeys(payloads):
            cid = uuid4()
            conn.execute(
                "INSERT INTO constraint_rule (id, kind, payload, source_id) "
                "VALUES (%s, 'must_not_contain', %s, %s)",
                (cid, p, record_id),
            )
            constraint_ids.append(cid)
    result = retract(conn, record_id, enqueue=enqueue, cause="delete")
    with conn.transaction():
        # The source text is gone from the record table. The constraint keeps
        # the payload so rebuilds can be checked against it.
        conn.execute(
            "UPDATE record SET deleted = true, text = '[deleted]', embedding = NULL WHERE id = %s",
            (record_id,),
        )
        emit(conn, "deleted", record_id=record_id, constraint_ids=[str(c) for c in constraint_ids])
    return {**result, "constraint_ids": constraint_ids}


# --------------------------------------------------------------------------
# lineage / diff / reports


def lineage(conn, record_id: UUID, version: int | None = None) -> dict:
    rec = q.get_record(conn, record_id, version)
    if rec is None:
        raise NotFound(f"record {record_id} not found")
    edges = q.lineage_edges(conn, rec["id"], rec["version"])
    keys = {(rec["id"], rec["version"])} | {(e["parent_id"], e["parent_version"]) for e in edges}
    nodes = {}
    for rid, ver in keys:
        r = q.get_record(conn, rid, ver)
        nodes[f"{rid}@{ver}"] = record_json(r)
    return {"root": f"{rec['id']}@{rec['version']}", "nodes": nodes, "edges": edges}


def diff(conn, record_id: UUID, from_version: int, to_version: int) -> dict:
    import difflib

    from server.llm import split_sentences

    a = q.get_record(conn, record_id, from_version)
    b = q.get_record(conn, record_id, to_version)
    if a is None or b is None:
        raise NotFound("version not found")
    a, b = record_json(a), record_json(b)
    lines = list(difflib.unified_diff(
        split_sentences(a["text"]), split_sentences(b["text"]),
        f"v{from_version}", f"v{to_version}", lineterm="",
    ))
    return {"id": record_id, "from": a, "to": b, "unified": lines}


def deletion_report(conn, record_id: UUID) -> dict:
    constraints = conn.execute(
        "SELECT id, kind, created_at FROM constraint_rule WHERE source_id = %s", (record_id,)
    ).fetchall()
    ids = [c["id"] for c in constraints]
    checks = conn.execute(
        "SELECT v.record_id, v.version, v.constraint_id, v.exact_hit, v.normalized_hit, "
        "v.paraphrase_hit, v.attempt, r.status, r.kind FROM verification v "
        "JOIN record r ON r.id = v.record_id AND r.version = v.version "
        "WHERE v.constraint_id = ANY(%s) ORDER BY v.at",
        (ids,),
    ).fetchall()
    # Latest versions that still contain a payload after normalization. Observations are
    # user input, so they are reported, not rewritten.
    residual = []
    for c in conn.execute(
        "SELECT id, payload FROM constraint_rule WHERE source_id = %s", (record_id,)
    ).fetchall():
        rows = conn.execute(
            "SELECT r.id, r.version, r.kind FROM record r JOIN record_head h "
            "ON h.id = r.id AND h.latest_version = r.version "
            "WHERE NOT r.deleted AND r.status <> 'retracted' "
            "AND position(%s in regexp_replace(lower(r.text), '[^a-z0-9]', '', 'g')) > 0",
            (normalize(c["payload"]),),
        ).fetchall()
        residual += [{**r, "constraint_id": c["id"]} for r in rows]
    failed = conn.execute(
        "SELECT id, record_id, result FROM rebuild_job WHERE state = 'failed' "
        "AND result->>'reason' = 'deletion_verifier'"
    ).fetchall()
    return {"source_id": record_id, "constraints": constraints, "checks": checks,
            "residual": residual, "failed_jobs": failed}


def jobs_summary(conn) -> dict:
    rows = conn.execute("SELECT state, count(*) AS n FROM rebuild_job GROUP BY state").fetchall()
    return {r["state"]: r["n"] for r in rows}

