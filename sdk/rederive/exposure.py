"""Exposure logging: remember which record versions each tool call read.

    @exposed(client)
    def lookup_profile(user_id): ...

Every client.read() inside the call carries the call's tool_call_id, and the
server logs the (tool_call_id, record_id, version) row. Later, GET
/exposure?stale_only=true lists the calls that acted on records that have
since been retracted or rebuilt with different content.
"""

import contextvars
import functools
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


@dataclass
class ToolCall:
    id: str
    name: str
    reads: list[tuple[str, int]] = field(default_factory=list)


_current: contextvars.ContextVar[ToolCall | None] = contextvars.ContextVar(
    "rederive_tool_call", default=None
)


def current_tool_call() -> ToolCall | None:
    return _current.get()


def exposed(client: Any = None, name: str | None = None) -> Callable[[F], F]:
    """Decorate a tool function so its record reads are logged.

    `client` is accepted for symmetry with the design doc; reads are logged by
    whichever client performs them.
    """

    def wrap(fn: F) -> F:
        tool_name = name or fn.__name__

        @functools.wraps(fn)
        def inner(*args, **kwargs):
            call = ToolCall(id=f"{tool_name}-{uuid.uuid4().hex[:12]}", name=tool_name)
            token = _current.set(call)
            try:
                return fn(*args, **kwargs)
            finally:
                _current.reset(token)
                inner.last_call = call  # type: ignore[attr-defined]

        return inner  # type: ignore[return-value]

    return wrap


class tool_call:
    """Context manager form of @exposed for ad-hoc blocks."""

    def __init__(self, name: str, call_id: str | None = None):
        self.call = ToolCall(id=call_id or f"{name}-{uuid.uuid4().hex[:12]}", name=name)

    def __enter__(self) -> ToolCall:
        self._token = _current.set(self.call)
        return self.call

    def __exit__(self, *exc) -> None:
        _current.reset(self._token)
