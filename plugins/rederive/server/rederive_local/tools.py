"""MCP tool definitions and handlers."""

from __future__ import annotations

import json
from typing import Any, Callable

from .engine import KINDS, Engine, RederiveError

REF = {"type": "string", "description": "A memory id, id@version, or name (such as \"profile\")."}
SCOPE = {
    "type": "string",
    "enum": ["project", "global"],
    "description": "project (default): visible in this project only. global: visible everywhere.",
}


def _tool(name: str, title: str, description: str, properties: dict, required: list[str],
          read_only: bool = False, destructive: bool = False) -> dict:
    return {
        "name": name,
        "title": title,
        "description": description,
        "inputSchema": {"type": "object", "properties": properties, "required": required,
                        "additionalProperties": False},
        "annotations": {"title": title, "readOnlyHint": read_only, "destructiveHint": destructive,
                        "idempotentHint": read_only, "openWorldHint": False},
    }


TOOLS = [
    _tool(
        "remember", "Remember a fact",
        "Store something the user said or a fact about them, in their words. Use for durable facts "
        "(job, preferences, names, dates), not for chit-chat. Returns the new memory's id.",
        {"text": {"type": "string", "description": "The fact, close to the user's words."},
         "topic": {"type": "string", "description": "Optional short topic such as work or billing."},
         "name": {"type": "string", "description": "Optional unique name to find it later."},
         "scope": SCOPE},
        ["text"],
    ),
    _tool(
        "recall", "Recall memories",
        "Search memory before answering questions about the user, or read one memory by id or name. "
        "Every recall is logged, so a later correction can show which answers relied on a wrong fact.",
        {"query": {"type": "string", "description": "What to look for."},
         "ref": REF,
         "kind": {"type": "string", "enum": ["observation", *KINDS]},
         "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
         "include_stale": {"type": "boolean", "default": False,
                           "description": "Also return memories waiting for a rebuild."}},
        [], read_only=True,
    ),
    _tool(
        "derive", "Save a derived memory",
        "Save a summary, belief, profile, or procedure that you wrote from other memories. List every "
        "memory you used in inputs and describe how you built it in instruction, so it can be rebuilt "
        "the same way if an input changes. Saving with an existing name replaces that memory with a "
        "new version.",
        {"inputs": {"type": "array", "items": {"type": "string"}, "minItems": 1,
                    "description": "Ids or names of the memories you used."},
         "instruction": {"type": "string",
                         "description": "How to build this record from its inputs, reusable later."},
         "text": {"type": "string", "description": "The record you wrote. Use only facts from the inputs."},
         "kind": {"type": "string", "enum": list(KINDS), "default": "summary"},
         "name": {"type": "string", "description": "Name such as profile or employer."},
         "replaces": REF,
         "scope": SCOPE},
        ["inputs", "instruction", "text"],
    ),
    _tool(
        "retract", "Retract a wrong memory",
        "Mark a memory as wrong. Every memory built on it goes stale. Returns rebuild_queue: rewrite "
        "each record with the rebuild tool, in order, until the queue is empty.",
        {"ref": REF}, ["ref"],
    ),
    _tool(
        "correct", "Correct a remembered fact",
        "Replace the text of a remembered fact (an observation) with the corrected version. Memories "
        "built on it go stale and appear in rebuild_queue.",
        {"ref": REF, "text": {"type": "string", "description": "The corrected fact."}},
        ["ref", "text"],
    ),
    _tool(
        "forget", "Forget a memory",
        "Delete a memory at the user's request. Its text is erased, and future rebuilds are checked so "
        "they cannot bring it back. Memories built on it appear in rebuild_queue. still_mentioned_in "
        "lists other remembered facts that repeat it; ask the user before forgetting those too.",
        {"ref": REF,
         "payload": {"type": "string",
                     "description": "Optional: only this part of the memory must be forgotten."}},
        ["ref"], destructive=True,
    ),
    _tool(
        "rebuild", "Submit a rebuilt memory",
        "Submit the rewritten text for one record from rebuild_queue. Follow its instruction and use "
        "only its current inputs. If the text says the same thing as before, the cascade stops there. "
        "Returns the next rebuild_queue.",
        {"ref": REF, "text": {"type": "string", "description": "The rewritten record."}},
        ["ref", "text"],
    ),
    _tool(
        "pending_rebuilds", "List pending rebuilds",
        "List stale memories that are ready to rewrite, with their instruction, current inputs, and "
        "previous text. Use it to finish a cascade that was interrupted.",
        {}, [], read_only=True,
    ),
    _tool(
        "why", "Explain a memory",
        "Show which memories and instructions produced a memory, all the way down to the original "
        "facts.",
        {"ref": REF}, ["ref"], read_only=True,
    ),
    _tool(
        "history", "Memory history",
        "Show every version of a memory and what changed in the last version.",
        {"ref": REF}, ["ref"], read_only=True,
    ),
    _tool(
        "exposure", "Exposure report",
        "List past recalls that returned a memory that has since been retracted, corrected, or "
        "rebuilt with different content. Use after a correction to find answers or actions that "
        "relied on the wrong fact.",
        {"stale_only": {"type": "boolean", "default": True}}, [], read_only=True,
    ),
]


def handlers(engine: Engine) -> dict[str, Callable[..., Any]]:
    return {
        "remember": engine.remember,
        "recall": engine.recall,
        "derive": engine.derive,
        "retract": engine.retract,
        "correct": engine.correct,
        "forget": engine.forget,
        "rebuild": engine.rebuild,
        "pending_rebuilds": lambda: {"rebuild_queue": engine.pending()},
        "why": engine.why,
        "history": engine.history,
        "exposure": lambda stale_only=True: {"calls": engine.exposure(stale_only)},
    }


def call(engine: Engine, name: str, arguments: dict | None) -> tuple[bool, str]:
    """Run one tool. Returns (is_error, text)."""
    fn = handlers(engine).get(name)
    if fn is None:
        return True, f"unknown tool {name!r}"
    try:
        result = fn(**(arguments or {}))
    except RederiveError as exc:
        return True, str(exc)
    except TypeError as exc:
        return True, f"bad arguments for {name}: {exc}"
    return False, json.dumps(result, ensure_ascii=False, indent=1)
