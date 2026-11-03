"""A live trace of every graph run, streamed to the browser as timed spans.

`CallTracer` is a LangChain callback handler, attached through the graph's config. It sees the
same events a LangSmith trace is built from, and forwards the ones worth drawing:

    turn   one graph run, i.e. one caller turn
    node   a graph node (greeter, order_status_tools, confirmation_email, ...)
    llm    a model call inside a specialist, with its time to first token
    tool   a tool call inside a ToolNode, marked "blocked" if the verification gate refused it

The browser turns these into the live graph view and the waterfall. Each span is sent twice,
once on start and once on end, on the "wismo.trace" topic.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from uuid import UUID

from langchain_core.callbacks import AsyncCallbackHandler

from .panel import TRACE_TOPIC, send
from .state import CallContext
from .tools import GateError

CANCELLED = (asyncio.CancelledError, GeneratorExit)


def now_ms() -> float:
    return round(time.time() * 1000, 1)


class CallTracer(AsyncCallbackHandler):
    def __init__(self, ctx: CallContext) -> None:
        self.ctx = ctx
        self.parents: dict[UUID, UUID | None] = {}  # every run seen, so spans can find their nearest drawn ancestor
        self.spans: dict[UUID, dict] = {}  # open spans that the browser knows about
        self.first_token: set[UUID] = set()

    # ------------------------------------------------------------------ helpers

    def _drawn_parent(self, parent: UUID | None) -> str | None:
        while parent is not None and parent not in self.spans:
            parent = self.parents.get(parent)
        return str(parent) if parent is not None else None

    async def _start(self, run_id: UUID, parent: UUID | None, kind: str, name: str, **extra: Any) -> None:
        span = {"type": "span", "phase": "start", "id": str(run_id), "parent": self._drawn_parent(parent),
                "kind": kind, "name": name, "at": now_ms(), **extra}
        self.spans[run_id] = span
        await send(self.ctx, span, TRACE_TOPIC)

    async def _end(self, run_id: UUID, status: str = "ok", **extra: Any) -> None:
        self.parents.pop(run_id, None)
        span = self.spans.pop(run_id, None)
        if span is None:
            return
        await send(self.ctx, {**span, "phase": "end", "at": now_ms(), "status": status, **extra}, TRACE_TOPIC)

    async def _error(self, run_id: UUID, error: BaseException) -> None:
        if isinstance(error, GateError):
            status = "blocked"
        elif isinstance(error, CANCELLED):
            status = "cancelled"
        else:
            status = "error"
        await self._end(run_id, status, error=str(error)[:160] or type(error).__name__)

    # ------------------------------------------------------------------ graph and nodes

    async def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None, tags=None, metadata=None, **kw):
        self.parents[run_id] = parent_run_id
        name = kw.get("name") or (serialized or {}).get("name") or ""
        if parent_run_id is None:
            await self._start(run_id, None, "turn", name or "graph")
        elif name and name == (metadata or {}).get("langgraph_node") and parent_run_id in self.spans:
            await self._start(run_id, parent_run_id, "node", name)

    async def on_chain_end(self, outputs, *, run_id, **kw):
        await self._end(run_id)

    async def on_chain_error(self, error, *, run_id, **kw):
        await self._error(run_id, error)

    # ------------------------------------------------------------------ model calls

    async def on_chat_model_start(self, serialized, messages, *, run_id, parent_run_id=None, metadata=None, **kw):
        self.parents[run_id] = parent_run_id
        model = (metadata or {}).get("ls_model_name") or kw.get("name") or "model"
        await self._start(run_id, parent_run_id, "llm", model)

    async def on_llm_new_token(self, token, *, run_id, **kw):
        if run_id in self.first_token or run_id not in self.spans:
            return
        self.first_token.add(run_id)
        await send(self.ctx, {"type": "first_token", "id": str(run_id), "at": now_ms()}, TRACE_TOPIC)

    async def on_llm_end(self, response, *, run_id, **kw):
        self.first_token.discard(run_id)
        await self._end(run_id)

    async def on_llm_error(self, error, *, run_id, **kw):
        self.first_token.discard(run_id)
        await self._error(run_id, error)

    # ------------------------------------------------------------------ tools

    async def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id=None, **kw):
        self.parents[run_id] = parent_run_id
        await self._start(run_id, parent_run_id, "tool", kw.get("name") or (serialized or {}).get("name") or "tool")

    async def on_tool_end(self, output, *, run_id, **kw):
        await self._end(run_id)

    async def on_tool_error(self, error, *, run_id, **kw):
        if isinstance(error, GateError):
            self.ctx.gate_blocks += 1
            span = self.spans.get(run_id) or {}
            await send(self.ctx, {"type": "gate", "tool": span.get("name"), "reason": str(error), "at": now_ms()},
                       TRACE_TOPIC)
        await self._error(run_id, error)
