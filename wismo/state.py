"""Graph state and per-call runtime context.

`CallState` is checkpointed by LangGraph and is the single source of truth for the call
(who is active, whether the caller is verified, which order is being discussed).
`CallContext` is the runtime context passed through `LLMAdapter(context=...)`. It holds
things that must not be checkpointed: the LiveKit room and the idempotency ledgers.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal

from langgraph.graph import MessagesState
from typing_extensions import NotRequired

import email_tool

AgentName = Literal["greeter", "order_status", "resolution"]
AGENTS: tuple[AgentName, ...] = ("greeter", "order_status", "resolution")
DISPLAY: dict[str, str] = {"greeter": "Greeter", "order_status": "Order Status", "resolution": "Resolution"}

# Which agent each agent's tools can hand the call to. Used both to restrict the graph's
# edges and to draw an accurate diagram.
HANDOFFS: dict[AgentName, list[AgentName]] = {
    "greeter": ["order_status"],
    "order_status": ["resolution"],
    "resolution": ["order_status"],
}


class CallState(MessagesState):
    """`messages` (with the add_messages reducer) comes from MessagesState."""

    active_agent: NotRequired[AgentName]
    order_id: NotRequired[str | None]
    phone: NotRequired[str | None]
    customer_id: NotRequired[int | None]
    customer_name: NotRequired[str | None]
    order_status: NotRequired[str | None]
    promised_date: NotRequired[str | None]
    verified: NotRequired[bool]
    verify_attempts: NotRequired[int]
    issue_summary: NotRequired[str | None]
    last_action: NotRequired[dict | None]  # the email is built ONLY from this
    email_sent: NotRequired[bool]
    email_pending: NotRequired[bool]  # set by Resolution actions, consumed by confirmation_email
    notes: NotRequired[list[str]]  # one-shot system notes for whoever speaks next


@dataclass
class CallContext:
    """Per-call runtime context. Never checkpointed."""

    room: Any = None  # rtc.Room
    publish: Callable[[dict], Awaitable[None]] | None = None  # tests capture panel payloads here
    send_email: Callable[..., Awaitable[dict]] = email_tool.send_confirmation_email
    # Idempotency ledgers. A side effect (ticket, email) is started once per key as a task that a
    # barge-in cannot cancel, so a retry after an interruption gets the same result instead of a duplicate.
    effects: dict[tuple, asyncio.Future] = field(default_factory=dict)
    emails: dict[tuple, asyncio.Future] = field(default_factory=dict)
    last_effect: dict | None = None  # latest completed action, even if its tool call was interrupted
    verify_attempts: int = 0  # incremented BEFORE the db await, so a barge-in can't refund an attempt
