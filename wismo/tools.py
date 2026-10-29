"""Every tool the agents can call.

Tools read the call state from `runtime.state` and write changes back as a single
`Command(update=...)`, so a tool result and its state change commit atomically.

The verification gate lives here, in code: tools that reveal order details or change
anything raise `ToolError` unless `state["verified"]` is true for that order. A prompt
can't talk its way past it.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Awaitable, Callable, Literal

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime
from langgraph.types import Command
from tavily import AsyncTavilyClient

import db

from .facts import describe_order, run_db, short_date, speak_event
from .panel import report
from .prompts import (
    MAX_VERIFY_ATTEMPTS,
    NOTE_BACK_TO_STATUS,
    NOTE_ORDER_FOUND,
    NOTE_PHONE_FOUND,
    NOTE_TO_RESOLUTION,
)
from .state import AgentName, CallContext, CallState

logger = logging.getLogger("wismo.tools")

Rt = ToolRuntime[CallContext, CallState]


class ToolError(Exception):
    """The message goes back to the model as an error ToolMessage."""


def require_verified(state: dict, order_id: str | None = None) -> str:
    if not state.get("verified") or not state.get("order_id"):
        raise ToolError(
            "The caller isn't verified yet. Ask for the last four digits of the phone "
            "number on the order and call verify_customer first."
        )
    if order_id and db.normalize_order_id(order_id) != state["order_id"]:
        raise ToolError(f"Only the verified order, {state['order_id']}, can be discussed or changed.")
    return state["order_id"]


def _reply(rt: Rt, text: str, **update: Any) -> Command:
    """A tool result and its state update in one atomic Command."""
    return Command(update={**update, "messages": [ToolMessage(text, tool_call_id=rt.tool_call_id)]})


def _add_note(state: dict, text: str) -> list[str]:
    return [*(state.get("notes") or []), text]


async def run_once(ctx: CallContext, key: tuple, make: Callable[[], Awaitable[dict]]) -> dict:
    """Run a side effect at most once per call.

    The effect runs as its own task and the caller awaits it through `shield`, so a barge-in
    that cancels the graph can't abandon it half-way. If the model asks again (a retry after an
    interruption), it gets the first result back instead of creating a second ticket.
    """
    fut = ctx.effects.get(key)
    if fut is None:
        fut = ctx.effects[key] = asyncio.ensure_future(make())
    try:
        return await asyncio.shield(fut)
    except Exception:
        ctx.effects.pop(key, None)  # a failed effect may be retried
        raise


# --------------------------------------------------------------------------- shared


@tool
async def escalate_to_human(reason: str, runtime: Rt) -> Command:
    """Create a support ticket and arrange for a human specialist to call the caller back.
    Use when the caller asks for a person, is very upset, or you can't solve the problem.

    Args:
        reason: One sentence on why the caller needs a human.
    """
    # Deliberately allowed for unverified callers, so someone who fails verification can still reach a person.
    s, ctx = runtime.state, runtime.context
    verified = bool(s.get("verified"))
    order_id = s.get("order_id") if verified else None
    notes = reason if verified else f"{reason} (unverified caller, gave order {s.get('order_id') or 'none'})"

    async def act() -> dict:
        ticket_id = await run_db(db.create_ticket, order_id, "escalation", notes)
        action = {"action": "escalation", "ticket_id": ticket_id, "reason": reason}
        if verified:
            ctx.last_effect = action
        return action

    action = await run_once(ctx, ("escalation", order_id), act)
    ticket_id = action["ticket_id"]
    update: dict = {}
    if verified:
        update = {
            "last_action": action,
            "email_sent": False,
            "email_pending": s.get("active_agent") == "resolution",
        }
    await report(ctx, {**s, **update}, f"Escalated to a human, ticket {ticket_id}")
    return _reply(
        runtime,
        f"Escalation ticket {ticket_id} created. Tell the caller a specialist will call them back "
        f"within one business day at the number on file, and give them ticket number {ticket_id}.",
        **update,
    )


# --------------------------------------------------------------------------- greeter


@tool
async def transfer_to_order_status(runtime: Rt, order_id: str | None = None, phone: str | None = None) -> Command | str:
    """Hand the call to the order specialist once the caller has confirmed their order number or phone number.

    Args:
        order_id: The order number as heard, for example "ORD-48213" or "48213".
        phone: The phone number on the account, digits only.
    """
    s, ctx = runtime.state, runtime.context
    update: dict[str, Any] = {"active_agent": "order_status"}

    if order_id:
        oid = db.normalize_order_id(order_id)
        if oid is None:
            return "That isn't a valid order number. Order numbers are O R D followed by five digits. Ask the caller to repeat it."
        if await run_db(db.get_order, oid) is None:
            return "No order with that number. Read back what you heard in chunks and ask the caller to repeat it."
        update["order_id"] = oid
        if oid != s.get("order_id"):
            update.update(verified=False, verify_attempts=0)
            ctx.verify_attempts = 0
        note = NOTE_ORDER_FOUND.format(oid=oid)
        captured = f"Captured order {oid}"
    elif phone:
        digits = db.digits_only(phone)
        if len(digits) < 10:
            return "That phone number is too short. Ask for the full number including area code."
        orders = await run_db(db.get_orders_by_phone, digits)
        if not orders:
            return "No account with that phone number. Read it back in chunks and ask the caller to check it."
        listed = ", ".join(f"{o['id']} placed {db.speakable_date(o['order_date'])}" for o in orders[:3])
        more = f", plus {len(orders) - 3} older ones" if len(orders) > 3 else ""
        update["phone"] = digits[-10:]
        note = NOTE_PHONE_FOUND.format(n=len(orders), s="s" if len(orders) != 1 else "", listed=listed, more=more)
        captured = f"Captured phone ending {digits[-4:]}"
    else:
        return "Ask the caller for their order number or the phone number on their account first."

    update["notes"] = _add_note(s, note)
    after = {**s, **update}
    await report(ctx, after, captured)
    await report(ctx, after, "Handed off to Order Status")
    return _reply(runtime, "Transferred.", **update)


@tool
async def search_web(query: str, runtime: Rt) -> str:
    """Search the web for a general question that isn't about a specific order, such as carrier holiday schedules or a major weather disruption. Never use it for order details.

    Args:
        query: A short search query.
    """
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        raise ToolError("Web search isn't available right now.")
    await report(runtime.context, runtime.state, f"Searched the web: {query}")
    result = await AsyncTavilyClient(api_key).search(
        query, max_results=3, include_answer=True, search_depth="basic", timeout=10
    )
    answer = result.get("answer") or " ".join(r["content"][:300] for r in result.get("results", []))
    if not answer:
        return "Nothing useful came back. Tell the caller you couldn't find that."
    return f"Search result. Summarise it in one spoken sentence with no URLs: {answer}"


# --------------------------------------------------------------------------- order status


@tool
async def lookup_order_by_id(order_id: str, runtime: Rt) -> Command | str:
    """Look up an order by its order number.

    Args:
        order_id: The order number, for example "ORD-48213".
    """
    s, ctx = runtime.state, runtime.context
    oid = db.normalize_order_id(order_id)
    order = await run_db(db.get_order, oid) if oid else None
    if order is None:
        await report(ctx, s, f"No order found for {order_id}")
        return "No order with that number. Read back what you heard in chunks and ask the caller to repeat it."
    update: dict = {}
    if oid != s.get("order_id"):
        update = {"order_id": oid, "verified": False, "verify_attempts": 0}
        ctx.verify_attempts = 0
    after = {**s, **update}
    await report(ctx, after, f"Looked up {oid}")
    if not after.get("verified"):
        text = f"Order {oid} exists. Verify the caller with the last four digits of their phone number before sharing anything else."
    else:
        text = await describe_order(order)
    return _reply(runtime, text, **update)


@tool
async def lookup_orders_by_phone(phone: str, runtime: Rt) -> str:
    """Find the order numbers on the account with this phone number.

    Args:
        phone: The phone number, digits only.
    """
    orders = await run_db(db.get_orders_by_phone, phone)
    await report(
        runtime.context,
        runtime.state,
        f"Found {len(orders)} order{'s' if len(orders) != 1 else ''} for phone ending {db.digits_only(phone)[-4:]}",
    )
    if not orders:
        return "No account with that phone number. Read it back in chunks and ask the caller to check it."
    listed = ", ".join(f"{o['id']} placed {db.speakable_date(o['order_date'])}" for o in orders[:3])
    more = f", plus {len(orders) - 3} older ones" if len(orders) > 3 else ""
    return f"Found {len(orders)} orders: {listed}{more}. Ask which one they're calling about, then verify them."


@tool
async def verify_customer(order_id: str, last_four_phone_digits: str, runtime: Rt) -> Command | str:
    """Verify the caller owns the order using the last four digits of the phone number on the account.

    Args:
        order_id: The order number being discussed.
        last_four_phone_digits: The four digits the caller said.
    """
    s, ctx = runtime.state, runtime.context
    oid = db.normalize_order_id(order_id)
    if oid is None:
        return "That order number isn't valid. Confirm it with the caller first."
    attempts = max(s.get("verify_attempts", 0), ctx.verify_attempts)
    if attempts >= MAX_VERIFY_ATTEMPTS:
        return "Too many failed attempts. Don't try again; offer to escalate to a human instead."
    # Counted before the database await, so interrupting the call can't hand back a free attempt.
    ctx.verify_attempts = attempts + 1

    customer = await run_db(db.verify_customer, oid, last_four_phone_digits)
    if customer is None:
        left = MAX_VERIFY_ATTEMPTS - (attempts + 1)
        await report(ctx, {**s, "verify_attempts": attempts + 1}, f"Verification failed ({left} left)")
        return _reply(
            runtime,
            f"Those digits don't match. {left} attempt{'s' if left != 1 else ''} left. Ask them to try again.",
            verify_attempts=attempts + 1,
        )

    ctx.verify_attempts = 0
    order = await run_db(db.get_order, oid)
    update = {
        "order_id": oid,
        "verified": True,
        "verify_attempts": 0,
        "customer_id": customer["id"],
        "customer_name": customer["name"],
        "order_status": order["status"],
        "promised_date": order["promised_date"],
    }
    await report(ctx, {**s, **update}, "Verification passed")
    first_name = customer["name"].split()[0]
    return _reply(
        runtime,
        f"Verified. The caller's first name is {first_name}; thank them by name. {await describe_order(order)}",
        **update,
    )


@tool
async def get_tracking_events(order_id: str, runtime: Rt) -> str:
    """Get the recent tracking history for the verified order, to explain where it is or why it's late.

    Args:
        order_id: The verified order number.
    """
    s = runtime.state
    oid = require_verified(s, order_id)
    events = await run_db(db.get_tracking_events, oid)
    await report(runtime.context, s, f"Fetched tracking history ({len(events)} events)")
    return " Then: ".join(f"{speak_event(e)}." for e in events[-4:])


@tool
async def transfer_to_resolution(issue_summary: str, runtime: Rt) -> Command:
    """Hand the call to the resolution specialist when the caller wants to reschedule, request a refund, report a problem, or speak to a person.

    Args:
        issue_summary: What the caller wants, in one sentence.
    """
    s = runtime.state
    require_verified(s)
    update = {
        "active_agent": "resolution",
        "issue_summary": issue_summary,
        "notes": _add_note(s, NOTE_TO_RESOLUTION.format(issue=issue_summary)),
    }
    await report(runtime.context, {**s, **update}, "Handed off to Resolution")
    return _reply(runtime, "Transferred.", **update)


# --------------------------------------------------------------------------- resolution


def _record(ctx: CallContext, action: dict) -> dict:
    ctx.last_effect = action
    return action


def _action_update(action: dict, **extra: Any) -> dict:
    return {"last_action": action, "email_sent": False, "email_pending": True, **extra}


@tool
async def reschedule_delivery(order_id: str, new_date: str, runtime: Rt) -> Command:
    """Move the delivery to a new date. Only call after the caller explicitly said yes to the exact date.

    Args:
        order_id: The verified order number.
        new_date: The new delivery date as YYYY-MM-DD.
    """
    s, ctx = runtime.state, runtime.context
    oid = require_verified(s, order_id)

    async def act() -> dict:
        result = await run_db(db.reschedule_delivery, oid, new_date)
        return _record(
            ctx, {"action": "reschedule", "new_date": result["new_date"], "ticket_id": result["ticket_id"]}
        )

    try:
        action = await run_once(ctx, ("reschedule", oid, new_date), act)
    except ValueError as e:
        raise ToolError(str(e)) from None
    update = _action_update(action, promised_date=action["new_date"])
    await report(ctx, {**s, **update}, f"Rescheduled delivery to {short_date(action['new_date'])}")
    return _reply(
        runtime,
        f"Done. Delivery is now {db.speakable_date(action['new_date'])}. Reference ticket {action['ticket_id']}.",
        **update,
    )


@tool
async def request_refund(order_id: str, reason: str, runtime: Rt) -> Command:
    """Open a refund request. Only call after the caller explicitly said yes to requesting a refund.

    Args:
        order_id: The verified order number.
        reason: Why the caller wants a refund.
    """
    s, ctx = runtime.state, runtime.context
    oid = require_verified(s, order_id)

    async def act() -> dict:
        ticket_id = await run_db(db.request_refund, oid, reason)
        return _record(ctx, {"action": "refund", "ticket_id": ticket_id, "reason": reason})

    try:
        action = await run_once(ctx, ("refund", oid), act)
    except ValueError as e:
        raise ToolError(str(e)) from None
    update = _action_update(action)
    await report(ctx, {**s, **update}, f"Refund requested, ticket {action['ticket_id']}")
    return _reply(
        runtime,
        f"Refund request {action['ticket_id']} opened. Refunds go back to the original payment method "
        "within 5 to 7 business days.",
        **update,
    )


@tool
async def create_ticket(
    order_id: str, type: Literal["lost_package", "damaged", "other"], notes: str, runtime: Rt
) -> Command:
    """Open a support ticket for a problem that isn't a reschedule or refund. Only call after the caller agreed.

    Args:
        order_id: The verified order number.
        type: The kind of problem.
        notes: One or two sentences describing it.
    """
    s, ctx = runtime.state, runtime.context
    oid = require_verified(s, order_id)

    async def act() -> dict:
        ticket_id = await run_db(db.create_ticket, oid, type, notes)
        return _record(ctx, {"action": "ticket", "ticket_id": ticket_id, "reason": notes})

    action = await run_once(ctx, ("ticket", oid, type), act)
    update = _action_update(action)
    await report(ctx, {**s, **update}, f"Ticket {action['ticket_id']} opened")
    return _reply(
        runtime, f"Ticket {action['ticket_id']} opened. The team will follow up within one business day.", **update
    )


@tool
async def transfer_back_to_order_status(runtime: Rt) -> Command:
    """Hand back to the order specialist for more questions about the order's status or tracking."""
    s = runtime.state
    update = {"active_agent": "order_status", "notes": _add_note(s, NOTE_BACK_TO_STATUS)}
    await report(runtime.context, {**s, **update}, "Handed off to Order Status")
    return _reply(runtime, "Transferred.", **update)


# Each agent only gets its own toolbox. The graph has one ToolNode per agent, so a tool
# from another agent isn't just hidden from the model, it can't be reached at all.
TOOLS: dict[AgentName, list] = {
    "greeter": [transfer_to_order_status, search_web, escalate_to_human],
    "order_status": [
        lookup_order_by_id,
        lookup_orders_by_phone,
        verify_customer,
        get_tracking_events,
        transfer_to_resolution,
        escalate_to_human,
    ],
    "resolution": [
        reschedule_delivery,
        request_refund,
        create_ticket,
        transfer_back_to_order_status,
        escalate_to_human,
    ],
}
