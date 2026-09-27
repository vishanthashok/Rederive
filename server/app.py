"""FastAPI routes for Rederive."""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

import psycopg
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from rederive.recipes import recipe_hash
from server import memory
from server.config import settings
from server.db import queries as q
from server.db.pool import apply_schema, get_pool, reset
from server.embed import get_embedder
from server.events import CHANNEL
from server.llm import get_llm

log = logging.getLogger("rederive.server")


def _make_queue():
    try:
        from server.workers.queue import RedisQueue

        queue = RedisQueue(settings.redis_url)
        queue.redis.ping()
        return queue
    except Exception as exc:  # noqa: BLE001
        # Jobs stay in Postgres. The worker's sweep picks them up.
        log.warning("redis unavailable (%s); jobs will be picked up by the worker sweep", exc)
        return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    apply_schema(get_pool())
    app.state.queue = _make_queue()
    yield


app = FastAPI(title="Rederive", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(memory.MemoryError_)
async def memory_error(_, exc: memory.MemoryError_):
    detail = exc.args[0] if exc.args else exc.__class__.__name__
    return JSONResponse(status_code=exc.status, content={"detail": detail})


def enqueue(jobs: list[tuple[int, int]]) -> None:
    queue = getattr(app.state, "queue", None)
    if queue is not None and jobs:
        queue.push(jobs)


class RecipeIn(BaseModel):
    template: str
    model: str = "default"
    params: dict[str, Any] = Field(default_factory=dict)


class ObserveIn(BaseModel):
    text: str
    meta: dict[str, Any] = Field(default_factory=dict)


class DeriveIn(BaseModel):
    inputs: list[str]  # "id" or "id@version"
    recipe: RecipeIn | str  # inline recipe or a registered hash
    kind: str = "summary"
    meta: dict[str, Any] = Field(default_factory=dict)
    target_id: UUID | None = None
    fan_in_k: int | None = None


class CorrectIn(BaseModel):
    text: str


class DeleteIn(BaseModel):
    payload: str | None = None


@app.get("/health")
def health() -> dict:
    return {"ok": True, "llm": settings.llm, "embedder": settings.embedder}


@app.post("/recipes")
def register_recipe(body: RecipeIn) -> dict:
    h = recipe_hash(body.template, body.model, body.params)
    with get_pool().connection() as conn:
        q.upsert_recipe(conn, h, body.template, body.model, body.params)
    return {"hash": h}


@app.get("/recipes/{h}")
def read_recipe(h: str) -> dict:
    with get_pool().connection() as conn:
        rec = q.get_recipe(conn, h)
    if rec is None:
        raise HTTPException(404, "recipe not found")
    return rec


@app.post("/records/observe")
def observe(body: ObserveIn) -> dict:
    with get_pool().connection() as conn:
        return memory.observe(conn, body.text, body.meta, get_embedder())


@app.post("/records/derive")
def derive(body: DeriveIn) -> dict:
    with get_pool().connection() as conn:
        if isinstance(body.recipe, str):
            stored = q.get_recipe(conn, body.recipe)
            if stored is None:
                raise HTTPException(404, "recipe hash not registered")
            recipe = {k: stored[k] for k in ("template", "model", "params")}
        else:
            recipe = body.recipe.model_dump()
        return memory.derive(
            conn, body.inputs, recipe, body.kind, get_llm(), get_embedder(),
            meta=body.meta, target_id=body.target_id, fan_in_k=body.fan_in_k, enqueue=enqueue,
        )


@app.post("/records/{record_id}/retract")
def retract(record_id: UUID) -> dict:
    with get_pool().connection() as conn:
        return memory.retract(conn, record_id, enqueue=enqueue)


@app.post("/records/{record_id}/correct")
def correct(record_id: UUID, body: CorrectIn) -> dict:
    with get_pool().connection() as conn:
        return memory.correct(conn, record_id, body.text, get_embedder(), enqueue=enqueue)


@app.post("/records/{record_id}/delete")
def delete(record_id: UUID, body: DeleteIn | None = None) -> dict:
    with get_pool().connection() as conn:
        return memory.delete(conn, record_id, body.payload if body else None, enqueue=enqueue)


@app.get("/records/{record_id}")
def read(
    record_id: UUID,
    version: int | None = None,
    tool_call_id: str | None = None,
    tool_name: str | None = None,
) -> dict:
    with get_pool().connection() as conn:
        return memory.read(conn, record_id, version, tool_call_id, tool_name)


@app.get("/records/{record_id}/versions")
def versions(record_id: UUID) -> list[dict]:
    with get_pool().connection() as conn:
        rows = q.get_versions(conn, record_id)
    if not rows:
        raise HTTPException(404, "record not found")
    return rows


@app.get("/records/{record_id}/lineage")
def lineage(record_id: UUID, version: int | None = None) -> dict:
    with get_pool().connection() as conn:
        return memory.lineage(conn, record_id, version)


@app.get("/records/{record_id}/diff")
def diff(record_id: UUID, from_: int = Query(alias="from"), to: int = Query()) -> dict:
    with get_pool().connection() as conn:
        return memory.diff(conn, record_id, from_, to)


@app.get("/records/{record_id}/deletion_report")
def deletion_report(record_id: UUID) -> dict:
    with get_pool().connection() as conn:
        return memory.deletion_report(conn, record_id)


@app.get("/graph")
def graph(user: str | None = None) -> dict:
    with get_pool().connection() as conn:
        return q.graph(conn, user)


@app.get("/exposure")
def exposure(stale_only: bool = False) -> list[dict]:
    with get_pool().connection() as conn:
        return q.exposures(conn, stale_only)


@app.get("/jobs")
def jobs(limit: int = 200) -> dict:
    with get_pool().connection() as conn:
        rows = conn.execute(
            "SELECT id, record_id, target_version, state, fence_token, depth, result, created_at, "
            "finished_at FROM rebuild_job ORDER BY id DESC LIMIT %s",
            (limit,),
        ).fetchall()
        return {"summary": memory.jobs_summary(conn), "jobs": rows}


@app.get("/events/recent")
def recent_events(after: int = 0, limit: int = 500) -> list[dict]:
    with get_pool().connection() as conn:
        return conn.execute(
            "SELECT id, kind, payload, at FROM event WHERE id > %s ORDER BY id LIMIT %s",
            (after, limit),
        ).fetchall()


@app.post("/admin/reset")
def admin_reset() -> dict:
    if not settings.allow_reset:
        raise HTTPException(403, "set REDERIVE_ALLOW_RESET=1 to enable reset")
    reset(get_pool())
    queue = getattr(app.state, "queue", None)
    if queue is not None:
        queue.clear()
    return {"ok": True}


@app.websocket("/events")
async def events_ws(ws: WebSocket) -> None:
    await ws.accept()
    aconn = await psycopg.AsyncConnection.connect(settings.database_url, autocommit=True)
    await aconn.execute(f"LISTEN {CHANNEL}")

    async def pump() -> None:
        async for note in aconn.notifies():
            await ws.send_text(note.payload)

    task = asyncio.create_task(pump())
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        task.cancel()
        await aconn.close()
