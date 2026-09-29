"""Memory operations for the plugin, with the chat model as the writer.

This follows server/memory.py, server/invalidate.py, and
server/workers/rebuild.py, with one change: the plugin never calls a model.
The chat model reads inputs, writes a derived record, and submits it. When a
memory is retracted, the engine marks every descendant stale, resolves the
rebuilds that need no writing (unchanged inputs, no inputs left), and hands
the chat model a queue of records to rewrite in topological order. Each
submitted rewrite goes through the same early cutoff as the server: if it
says the same thing, its children are skipped.
"""

from __future__ import annotations

import difflib
import os
import re
import uuid
from collections import Counter
from typing import Any

from . import text as T
from .store import Store, now

KINDS = ("summary", "belief", "procedure", "reflection")
HOST_MODEL = "host"
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class RederiveError(Exception):
    pass


class Engine:
    def __init__(self, store: Store, project: str | None = None):
        self.store = store
        self.project = project if project is not None else os.getcwd()

    # ------------------------------------------------------------------
    # references and output

    def resolve(self, ref: str, allow_deleted: bool = False) -> dict:
        """Find a record by id, id@version, or name. Returns that version."""
        ref = (ref or "").strip()
        rid, _, ver = ref.partition("@")
        if UUID_RE.match(rid):
            rec = self.store.get_record(rid, int(ver) if ver else None)
        else:
            rec = self._by_name(ref)
        if rec is None:
            raise RederiveError(f"no memory found for {ref!r}")
        if rec["deleted"] and not allow_deleted:
            raise RederiveError(f"memory {ref!r} was deleted")
        return rec

    def _by_name(self, name: str) -> dict | None:
        matches = [
            r for r in self.store.latest_records()
            if r["meta"].get("name") == name and not r["deleted"] and self._visible(r)
        ]
        # Prefer this project's record over a global one, then the newest.
        matches.sort(key=lambda r: (r["meta"].get("project") == self.project, r["created_at"]))
        return matches[-1] if matches else None

    def _visible(self, rec: dict) -> bool:
        project = rec["meta"].get("project")
        return project in (None, self.project)

    @staticmethod
    def public(rec: dict) -> dict:
        meta = rec["meta"]
        out = {
            "id": rec["id"],
            "version": rec["version"],
            "kind": rec["kind"],
            "status": rec["status"],
            "text": "[deleted]" if rec["deleted"] else rec["text"],
        }
        for key in ("name", "topic"):
            if meta.get(key):
                out[key] = meta[key]
        return out

    def _label(self, rec: dict) -> str:
        return rec["meta"].get("name") or rec["id"]

    def _check_constraints(self, text: str) -> None:
        for c in self.store.active_constraints():
            how = T.reveals(text, c["payload"])
            if how:
                # Never echo the deleted payload back into the conversation.
                raise RederiveError(
                    f"this text still contains information the user deleted (from memory "
                    f"{c['source_id']}, {how} match). Rewrite it without that information."
                )

    # ------------------------------------------------------------------
    # remember / derive

    def remember(self, text: str, topic: str | None = None, name: str | None = None,
                 scope: str = "project") -> dict:
        text = (text or "").strip()
        if not text:
            raise RederiveError("text is empty")
        meta = self._meta(topic=topic, name=name, scope=scope)
        rid = str(uuid.uuid4())
        with self.store.transaction():
            self.store.insert_record(rid, 1, "observation", text, T.embed(text), None, 1, meta)
            self.store.insert_head(rid)
        return self.public(self.store.get_record(rid))

    def _meta(self, scope: str = "project", **values: Any) -> dict:
        meta = {k: v for k, v in values.items() if v}
        if scope != "global":
            meta["project"] = self.project
        return meta

    def derive(self, inputs: list[str], instruction: str, text: str, kind: str = "summary",
               name: str | None = None, replaces: str | None = None, scope: str = "project") -> dict:
        if kind not in KINDS:
            raise RederiveError(f"kind must be one of {', '.join(KINDS)}")
        if not inputs:
            raise RederiveError("derive needs at least one input memory")
        text, instruction = (text or "").strip(), (instruction or "").strip()
        if not text or not instruction:
            raise RederiveError("text and instruction are required")

        parents = []
        for ref in inputs:
            rec = self.resolve(ref)
            if rec["status"] != "valid":
                raise RederiveError(
                    f"input {ref!r} is {rec['status']}. Run pending_rebuilds and rebuild it first, "
                    "or leave it out."
                )
            parents.append(rec)
        parent_ids = [p["id"] for p in parents]

        target = None
        if replaces:
            target = self.resolve(replaces)
        elif name:
            target = self._by_name(name)
        if target is not None:
            if target["kind"] == "observation":
                raise RederiveError(
                    f"{self._label(target)!r} is a remembered fact. Change it with correct, or give "
                    "this derived memory a different name."
                )
            if target["id"] in parent_ids or self.store.is_ancestor(target["id"], parent_ids):
                raise RederiveError(f"cycle: an input depends on {self._label(target)!r}")

        self._check_constraints(text)
        rhash = T.recipe_hash(instruction, HOST_MODEL, {})
        meta = self._meta(name=name, scope=scope)
        stale: list[dict] = []
        with self.store.transaction():
            self.store.upsert_recipe(rhash, instruction, HOST_MODEL, {})
            if target is None:
                rid, version = str(uuid.uuid4()), 1
                self.store.insert_head(rid)
            else:
                head = self.store.get_head(target["id"])
                old = self.store.get_record(target["id"], head["latest_version"])
                rid, version = target["id"], head["latest_version"] + 1
                meta = {**old["meta"], **meta}
                self.store.set_latest(rid, version)
                self.store.bump_fence(rid)
                if old["status"] != "retracted":
                    self.store.set_status(rid, old["version"], "superseded")
            self.store.insert_record(rid, version, kind, text, T.embed(text), rhash, version, meta)
            self.store.insert_edges(rid, version, [(p["id"], p["version"], i) for i, p in enumerate(parents)])
            if target is not None:
                stale = self._invalidate(rid, [version - 1], cause=f"new_version:{rid}")
        out = {**self.public(self.store.get_record(rid)), "inputs": [self._label(p) for p in parents]}
        if target is not None:
            out.update(self._cascade(f"new_version:{rid}", stale))
        return out

    # ------------------------------------------------------------------
    # invalidation

    def _invalidate(self, record_id: str, versions: list[int], cause: str) -> list[dict]:
        """Mark every live descendant stale and queue a rebuild job for it.

        Runs inside the caller's transaction. Each stale record gets a new
        fence token, which also voids any older job for it.
        """
        stale = []
        for row in self.store.descendants(record_id, versions):
            rec = self.store.get_record(row["id"], row["version"])
            if rec is None or rec["status"] not in ("valid", "stale"):
                continue
            self.store.set_status(row["id"], row["version"], "stale")
            fence = self.store.bump_fence(row["id"])
            self.store.execute(
                "UPDATE rebuild_job SET state = 'discarded', finished_at = ? "
                "WHERE record_id = ? AND state = 'queued'",
                (now(), row["id"]),
            )
            self.store.execute(
                "INSERT INTO rebuild_job (record_id, target_version, fence_token, depth, cause, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (row["id"], row["version"] + 1, fence, row["depth"], cause, now()),
            )
            stale.append({"id": row["id"], "version": row["version"], "depth": row["depth"]})
        return stale

    def retract(self, ref: str, cause: str = "retract") -> dict:
        rec = self.resolve(ref)
        rid = rec["id"]
        with self.store.transaction():
            self.store.execute(
                "UPDATE record SET status = 'retracted' WHERE id = ? AND status <> 'superseded'", (rid,)
            )
            versions = [v["version"] for v in self.store.get_versions(rid)]
            self.store.bump_fence(rid)
            self.store.execute(
                "UPDATE rebuild_job SET state = 'discarded', finished_at = ? "
                "WHERE record_id = ? AND state = 'queued'",
                (now(), rid),
            )
            stale = self._invalidate(rid, versions, cause=f"{cause}:{rid}")
        return {"retracted": self._label(rec), **self._cascade(f"{cause}:{rid}", stale)}

    def correct(self, ref: str, text: str) -> dict:
        text = (text or "").strip()
        if not text:
            raise RederiveError("text is empty")
        old = self.resolve(ref)
        if old["kind"] != "observation":
            raise RederiveError(
                "only remembered facts (observations) can be corrected. Derived memories rebuild "
                "from their inputs: correct or retract an input instead."
            )
        rid = old["id"]
        with self.store.transaction():
            head = self.store.get_head(rid)
            old = self.store.get_record(rid, head["latest_version"])
            version = old["version"] + 1
            self.store.set_status(rid, old["version"], "superseded")
            self.store.insert_record(rid, version, "observation", text, T.embed(text), None, version,
                                     old["meta"])
            self.store.set_latest(rid, version)
            self.store.bump_fence(rid)
            stale = self._invalidate(rid, [old["version"]], cause=f"correct:{rid}")
        return {**self.public(self.store.get_record(rid)), **self._cascade(f"correct:{rid}", stale)}

    def forget(self, ref: str, payload: str | None = None) -> dict:
        rec = self.resolve(ref)
        rid = rec["id"]
        payloads = [payload] if payload else [rec["text"], *T.sensitive_spans(rec["text"])]
        with self.store.transaction():
            for p in dict.fromkeys(payloads):
                self.store.execute(
                    "INSERT INTO constraint_rule (id, kind, payload, source_id, created_at) "
                    "VALUES (?, 'must_not_contain', ?, ?, ?)",
                    (str(uuid.uuid4()), p, rid, now()),
                )
            out = self.retract(ref, cause="forget")
            # The source text is gone. The constraint keeps the payload so
            # rebuilds can be checked against it.
            self.store.execute(
                "UPDATE record SET deleted = 1, text = '[deleted]', embedding = NULL WHERE id = ?", (rid,)
            )
        # Other remembered facts that still mention it. They are user input, so
        # they are reported, not rewritten.
        residual = []
        for r in self.store.latest_records():
            if r["deleted"] or r["status"] in ("retracted", "superseded") or r["kind"] != "observation":
                continue
            if any(T.reveals(r["text"], p) for p in payloads):
                residual.append(self.public(r))
        out["forgotten"] = out.pop("retracted")
        out["still_mentioned_in"] = residual
        return out

    # ------------------------------------------------------------------
    # the rebuild queue

    def _plan(self, job: dict) -> tuple[str, dict | None, list]:
        """Classify a queued job: ok, wait, or a final state it was moved to."""
        rid = job["record_id"]
        head = self.store.get_head(rid)
        if head["fence_token"] != job["fence_token"]:
            return self.store.finish_job(job["id"], "discarded", reason="fence_token_advanced"), None, []
        cur = self.store.get_record(rid, head["latest_version"])
        if cur["status"] != "stale":
            return self.store.finish_job(job["id"], "discarded", reason=f"record_is_{cur['status']}"), None, []
        plan = []
        for e in self.store.parent_edges(rid, cur["version"]):
            used = self.store.get_record(e["parent_id"], e["parent_version"])
            latest = self.store.get_record(e["parent_id"])
            if latest["status"] == "stale":
                if self.store.one("SELECT 1 FROM rebuild_job WHERE record_id = ? AND state = 'queued'",
                                  (latest["id"],)):
                    return "wait", cur, []
                return self.store.finish_job(job["id"], "failed", reason="parent_failed",
                                             parent_id=latest["id"]), cur, []
            plan.append((used, latest, e["position"]))
        return "ok", cur, plan

    @staticmethod
    def _live(plan: list) -> list:
        return [p for p in plan if p[1]["status"] == "valid" and not p[1]["deleted"]]

    def _auto(self, job: dict) -> str:
        """Resolve a job that needs no writing. Returns its state, 'wait', or 'needs_text'."""
        with self.store.transaction():
            state, cur, plan = self._plan(job)
            if state != "ok":
                return state
            rid, live = cur["id"], self._live(plan)
            if len(live) == len(plan) and all(
                u["content_version"] == l["content_version"] for u, l, _ in live
            ):
                # No input changed in content. Point at the new parent versions.
                self.store.set_status(rid, cur["version"], "valid")
                self.store.insert_edges(
                    rid, cur["version"],
                    [(l["id"], l["version"], pos) for u, l, pos in live if l["version"] != u["version"]],
                    alias=True,
                )
                return self.store.finish_job(job["id"], "skipped", reason="inputs_equivalent")
            if not live:
                # Every input is gone, so the record has no support left.
                self.store.set_status(rid, cur["version"], "retracted")
                return self.store.finish_job(job["id"], "done", reason="no_inputs", retracted=True)
            return "needs_text"

    def pending(self) -> list[dict]:
        """Resolve what needs no writing, then list records ready to rewrite."""
        for _ in range(1000):
            outcomes = [self._auto(job) for job in self.store.queued_jobs()]
            if not any(o not in ("wait", "needs_text") for o in outcomes):
                break
        tasks = []
        for job in self.store.queued_jobs():
            state, cur, plan = self._plan(job)
            if state != "ok":
                continue
            recipe = self.store.get_recipe(cur["recipe_hash"])
            live = self._live(plan)
            tasks.append({
                "id": cur["id"],
                "name": cur["meta"].get("name"),
                "kind": cur["kind"],
                "instruction": recipe["template"] if recipe else "",
                "inputs": [{"id": l["id"], "name": l["meta"].get("name"), "text": l["text"]}
                           for _, l, _ in live],
                "dropped_inputs": [self._label(u) for u, l, _ in plan
                                   if l["id"] not in {x["id"] for _, x, _ in live}],
                "previous_text": cur["text"],
            })
        return tasks

    def _cascade(self, cause: str, stale: list[dict]) -> dict:
        queue = self.pending()
        rows = self.store.all(
            "SELECT state FROM rebuild_job WHERE cause = ?", (cause,)
        )
        tally = Counter(r["state"] for r in rows)
        return {
            "stale_count": len(stale),
            "tally": {"waiting_for_rewrite": tally.pop("queued", 0), **tally},
            "rebuild_queue": queue,
        }

    def rebuild(self, ref: str, text: str) -> dict:
        text = (text or "").strip()
        if not text:
            raise RederiveError("text is empty")
        rec = self.resolve(ref)
        rid = rec["id"]
        self.pending()
        job = self.store.one(
            "SELECT * FROM rebuild_job WHERE record_id = ? AND state = 'queued' ORDER BY id DESC", (rid,)
        )
        if job is None:
            raise RederiveError(f"{self._label(rec)!r} has no pending rebuild")
        self._check_constraints(text)
        with self.store.transaction():
            state, cur, plan = self._plan(job)
            if state == "wait":
                raise RederiveError(
                    f"rebuild the inputs of {self._label(rec)!r} first; see pending_rebuilds"
                )
            if state != "ok":
                raise RederiveError(f"this rebuild is no longer needed ({state}); see pending_rebuilds")
            live = self._live(plan)
            equal, similarity, method = T.decide(cur["text"], text)
            version = self.store.get_head(rid)["latest_version"] + 1
            content_version = cur["content_version"] if equal else version
            self.store.insert_record(rid, version, cur["kind"], text, T.embed(text), cur["recipe_hash"],
                                     content_version, cur["meta"])
            self.store.insert_edges(rid, version, [(l["id"], l["version"], pos) for _, l, pos in live])
            self.store.set_status(rid, cur["version"], "equivalent" if equal else "superseded")
            self.store.set_latest(rid, version)
            outcome = "cut_off" if equal else "done"
            self.store.finish_job(job["id"], outcome, new_version=version,
                                  similarity=round(similarity, 4), method=method)
        cause = job["cause"] or ""
        return {
            "rebuilt": self._label(rec),
            "version": version,
            "outcome": "same meaning, cascade stops here" if equal else "changed, dependents rebuild",
            "similarity": round(similarity, 4),
            "method": method,
            **self._cascade(cause, []),
        }

    # ------------------------------------------------------------------
    # reads

    def recall(self, query: str | None = None, ref: str | None = None, kind: str | None = None,
               limit: int = 10, include_stale: bool = False) -> dict:
        call_id = f"recall-{uuid.uuid4().hex[:12]}"
        if ref:
            rec = self.resolve(ref)
            results = [rec]
        else:
            allowed = {"valid", "stale"} if include_stale else {"valid"}
            candidates = [
                r for r in self.store.latest_records()
                if not r["deleted"] and r["status"] in allowed and self._visible(r)
                and (kind is None or r["kind"] == kind)
            ]
            if query:
                qv = T.embed(query)
                words = set(T.TOKEN_RE.findall(query.lower()))

                def score(r: dict) -> float:
                    hits = words & set(T.TOKEN_RE.findall(r["text"].lower()))
                    return T.cosine(qv, r["embedding"]) + (len(hits) / len(words) if words else 0)

                candidates.sort(key=score, reverse=True)
            else:
                candidates.reverse()  # newest first
            results = candidates[: max(1, min(int(limit or 10), 50))]
        with self.store.transaction():
            for r in results:
                self.store.execute(
                    "INSERT INTO exposure (call_id, tool_name, record_id, version, at) VALUES (?, ?, ?, ?, ?)",
                    (call_id, "recall", r["id"], r["version"], now()),
                )
        return {"call_id": call_id, "memories": [self.public(r) for r in results]}

    def why(self, ref: str) -> dict:
        """Every input above a record version, newest edge per parent."""
        rec = self.resolve(ref, allow_deleted=True)
        root = (rec["id"], rec["version"])
        nodes, edges, frontier, seen = {}, [], [root], {root}
        while frontier:
            rid, ver = frontier.pop(0)
            r = self.store.get_record(rid, ver)
            recipe = self.store.get_recipe(r["recipe_hash"])
            node = self.public(r)
            if recipe:
                node["instruction"] = recipe["template"]
            nodes[f"{rid}@{ver}"] = node
            for e in self.store.parent_edges(rid, ver):
                key = (e["parent_id"], e["parent_version"])
                edges.append({"child": f"{rid}@{ver}", "parent": f"{key[0]}@{key[1]}",
                              "alias": e["alias"]})
                if key not in seen:
                    seen.add(key)
                    frontier.append(key)
        return {"root": f"{root[0]}@{root[1]}", "nodes": nodes, "edges": edges}

    def history(self, ref: str) -> dict:
        rec = self.resolve(ref, allow_deleted=True)
        versions = self.store.get_versions(rec["id"])
        out = {
            "id": rec["id"],
            "name": rec["meta"].get("name"),
            "versions": [
                {"version": v["version"], "status": v["status"], "created_at": v["created_at"],
                 "text": "[deleted]" if v["deleted"] else v["text"]}
                for v in versions
            ],
        }
        if len(versions) > 1:
            a, b = out["versions"][-2], out["versions"][-1]
            out["last_change"] = [
                line for line in difflib.unified_diff(
                    T.split_sentences(a["text"]), T.split_sentences(b["text"]),
                    f"v{a['version']}", f"v{b['version']}", lineterm="",
                )
                if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
            ]
        return out

    def exposure(self, stale_only: bool = True) -> list[dict]:
        """Past recalls that returned a version that is no longer current."""
        rows = self.store.all(
            """
            SELECT x.call_id, x.tool_name, x.at, x.record_id, x.version, r.meta,
                   r.deleted, r.text AS read_text, r.status AS read_status,
                   l.version AS latest_version, l.status AS latest_status,
                   l.deleted AS latest_deleted, l.text AS latest_text,
                   CASE
                     WHEN l.status = 'valid' AND l.content_version = r.content_version THEN 'valid'
                     WHEN l.status = 'stale' AND l.content_version = r.content_version
                          AND r.status <> 'retracted' THEN 'pending'
                     ELSE 'invalid'
                   END AS state
            FROM exposure x
            JOIN record r ON r.id = x.record_id AND r.version = x.version
            JOIN record_head h ON h.id = x.record_id
            JOIN record l ON l.id = h.id AND l.version = h.latest_version
            ORDER BY x.at DESC, x.call_id
            """
        )
        out = []
        for row in rows:
            if stale_only and row["state"] == "valid":
                continue
            out.append({
                "call_id": row["call_id"],
                "at": row["at"],
                "memory": row["meta"].get("name") or row["record_id"],
                "read_version": row["version"],
                "read_text": "[deleted]" if row["deleted"] else row["read_text"],
                "state": row["state"],
                "latest_version": row["latest_version"],
                "latest_text": "[deleted]" if row["latest_deleted"] else row["latest_text"],
            })
        return out
