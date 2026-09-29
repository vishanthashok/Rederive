#!/usr/bin/env python3
"""Rederive MCP server over stdio.

Speaks MCP (JSON-RPC 2.0, one message per line) with the Python standard
library only. Memory is stored in a local SQLite file, by default
~/.rederive/memory.db (override with REDERIVE_DB). The server makes no
network requests: the chat app's own model writes every summary and
rebuild, and this server stores them and tracks what depends on what.

Run: python3 rederive_mcp.py
"""

from __future__ import annotations

import json
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rederive_local import __version__  # noqa: E402
from rederive_local.engine import Engine  # noqa: E402
from rederive_local.store import Store, default_path  # noqa: E402
from rederive_local.tools import TOOLS, call  # noqa: E402

PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")

INSTRUCTIONS = (
    "Rederive is long-term memory with lineage. recall before answering questions about the user. "
    "remember durable facts they state. Save summaries such as a profile with derive, listing the "
    "memories you used. When the user says a fact is wrong, call retract or correct, then rewrite "
    "every record in rebuild_queue with rebuild until the queue is empty. Use forget when the user "
    "asks to delete something."
)


class MethodNotFound(Exception):
    pass


def log(message: str) -> None:
    print(f"rederive: {message}", file=sys.stderr, flush=True)


class Server:
    def __init__(self, engine: Engine):
        self.engine = engine

    def handle(self, msg: dict) -> dict | None:
        method, msg_id = msg.get("method"), msg.get("id")
        if method is None:
            return None  # a response to something we never send
        if msg_id is None:
            return None  # notifications need no reply
        params = msg.get("params") or {}
        try:
            result = self.dispatch(method, params)
        except MethodNotFound:
            return {"jsonrpc": "2.0", "id": msg_id,
                    "error": {"code": -32601, "message": f"method not found: {method}"}}
        except Exception as exc:  # noqa: BLE001
            log(traceback.format_exc())
            return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32603, "message": str(exc)}}
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    def dispatch(self, method: str, params: dict) -> dict:
        if method == "initialize":
            requested = params.get("protocolVersion")
            return {
                "protocolVersion": requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "rederive", "title": "Rederive", "version": __version__},
                "instructions": INSTRUCTIONS,
            }
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": TOOLS}
        if method == "tools/call":
            is_error, text = call(self.engine, params.get("name", ""), params.get("arguments"))
            return {"content": [{"type": "text", "text": text}], "isError": is_error}
        raise MethodNotFound(method)


def main() -> None:
    # UTF-8 and bare newlines on every platform, Windows included.
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    path = default_path()
    engine = Engine(Store(path))
    log(f"memory at {path}, project {engine.project}")
    server = Server(engine)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            reply = server.handle(msg) if isinstance(msg, dict) else {
                "jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "batches not supported"}}
        if reply is not None:
            sys.stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
