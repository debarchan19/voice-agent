"""The LangGraph brain: one StateGraph, three specialist agents, a toolbox each.

    START -> begin_turn -> greeter | order_status | resolution | confirmation_email
    each agent -> its own ToolNode -> back to whichever agent is now active

`begin_turn` and `confirmation_email` are plain code (no LLM). Only the three specialists
call the model, and the text they stream through `runtime.stream_writer` is the only thing
that reaches the caller's ears (the voice layer reads the graph in "custom" stream mode).
"""

from __future__ import annotations

import asyncio
import logging

from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.runtime import Runtime

import db

from .facts import describe_action, long_date, run_db
from .panel import report
from .prompts import (
    FALLBACK_SPEECH,
    NOTE_EARLIER_ACTION,
    NOTE_EARLIER_EMAIL,
    NOTE_EMAIL_FAILED,
    NOTE_EMAIL_SENT,
    ROLES,
    voice_rules,
)
from .state import AGENTS, HANDOFFS, AgentName, CallContext, CallState
from .tools import TOOLS, ToolError

logger = logging.getLogger("wismo.graph")

MAX_TOOL_ROUNDS = 4  # per agent, per caller turn
IN_FLIGHT_TIMEOUT = 10  # seconds begin_turn waits for an interrupted side effect to finish


# --------------------------------------------------------------------------- prompt building


def summary(state: dict) -> str:
    parts = []
    if state.get("order_id"):
        parts.append(f"order number {state['order_id']}")
    if state.get("phone"):
        parts.append(f"phone number {state['phone']}")
    if state.get("verified"):
        parts.append(f"caller verified as {state.get('customer_name')}, order status {state.get('order_status')}")
    else:
        parts.append("caller not verified yet")
    if state.get("issue_summary"):
        parts.append(f"issue: {state['issue_summary']}")
    return "; ".join(parts) + "."


def _this_turn(msgs: list[AnyMessage]) -> list[AnyMessage]:
    """Messages after the caller's latest words."""
    for i in range(len(msgs) - 1, -1, -1):
        if isinstance(msgs[i], HumanMessage):
            return msgs[i + 1 :]
    return msgs


def spoken_this_turn(msgs: list[AnyMessage]) -> str:
    return " ".join(m.text for m in _this_turn(msgs) if isinstance(m, AIMessage) and m.name in AGENTS and m.text)


def system_prompt(agent: AgentName, state: dict) -> str:
    prompt = f"{voice_rules()}\n\n{ROLES[agent]}\n\nContext from earlier in this call: {summary(state)}"
    if state.get("notes"):
        prompt += "\n\nYou have just taken over the call, or something just happened. " + " ".join(state["notes"])
    said = spoken_this_turn(state["messages"])
    if said:
        prompt += f"\n\nYou already said this to the caller this turn, so don't repeat it: '{said}'"
    return prompt


def view_for(agent: AgentName, msgs: list[AnyMessage]) -> list[AnyMessage]:
    """The conversation as one agent should see it.

    Keeps what was said plus this agent's own tool exchanges, and drops other agents' tool calls
    so each prompt stays small and on-role. Text spoken before a tool call in an earlier turn is
    blanked, because LiveKit's transcript already carries it (otherwise it would appear twice).
    """
    last_human = max((i for i, m in enumerate(msgs) if isinstance(m, HumanMessage)), default=-1)
    out: list[AnyMessage] = []
    foreign: set[str] = set()
    for i, m in enumerate(msgs):
        if isinstance(m, SystemMessage):
            continue
        if isinstance(m, AIMessage) and m.tool_calls:
            if m.name != agent:
                foreign |= {tc["id"] for tc in m.tool_calls}
                continue
            if i < last_human and m.text:
                m = m.model_copy(update={"content": _tool_use_only(m)})
        if isinstance(m, ToolMessage) and m.tool_call_id in foreign:
            continue
        out.append(m)
    return out


def _tool_use_only(m: AIMessage):
    if isinstance(m.content, list):
        return [b for b in m.content if not (isinstance(b, dict) and b.get("type") == "text")]
    return ""


# --------------------------------------------------------------------------- nodes


async def begin_turn(state: CallState, runtime: Runtime[CallContext]) -> dict:
    """Plain code, no LLM: reconcile the checkpoint with what LiveKit just re-sent.

    The voice layer sends its whole transcript every turn. It's merged into the checkpoint
    by message id, so this node tidies up:
      * LiveKit's own copy of what was said is authoritative (and is truncated if the caller
        barged in), so the graph's duplicate final replies are dropped;
      * LiveKit's system message is dropped, since each specialist builds its own prompt;
      * a tool call left without a result by an interruption is dropped, because the model
        API rejects a tool_use with no tool_result;
      * a side effect (ticket, email) that finished after an interruption is folded into state.
    """
    ctx = runtime.context
    in_flight = [f for f in [*ctx.effects.values(), *ctx.emails.values()] if not f.done()]
    if in_flight:
        await asyncio.wait(in_flight, timeout=IN_FLIGHT_TIMEOUT)

    msgs = state["messages"]
    answered = {m.tool_call_id for m in msgs if isinstance(m, ToolMessage)}
    update: dict = {
        "messages": [
            RemoveMessage(id=m.id)
            for m in msgs
            if m.id
            and (
                isinstance(m, SystemMessage)
                or (isinstance(m, AIMessage) and m.name in AGENTS and not m.tool_calls)
                or (isinstance(m, AIMessage) and any(tc["id"] not in answered for tc in m.tool_calls))
            )
        ]
    }

    # A side effect that completed after the caller cut in, so its tool call never returned.
    notes = list(state.get("notes") or [])
    last = ctx.last_effect
    current = state.get("last_action") or {}
    if last and state.get("verified") and (last["action"], last["ticket_id"]) != (
        current.get("action"),
        current.get("ticket_id"),
    ):
        update.update(last_action=last, email_sent=False, email_pending=state.get("active_agent") == "resolution")
        notes.append(NOTE_EARLIER_ACTION.format(action=describe_action(last)))
        current = last
    if current:
        done = ctx.emails.get((current["action"], current["ticket_id"]))
        if done is not None and done.done() and not done.cancelled() and done.exception() is None and done.result()["ok"]:
            if not state.get("email_sent"):
                update.update(email_sent=True, email_pending=False)
                notes.append(NOTE_EARLIER_EMAIL)
    if notes != list(state.get("notes") or []):
        update["notes"] = notes

    update["verify_attempts"] = max(state.get("verify_attempts", 0), ctx.verify_attempts)
    return update


def route_after_begin(state: CallState) -> str:
    agent = state.get("active_agent", "greeter")
    if agent == "resolution" and state.get("email_pending") and state.get("verified"):
        return "confirmation_email"
    return agent


def make_specialist(agent: AgentName, model):
    # One tool call at a time: parallel calls can both write the same state key in one step,
    # which LangGraph rejects (and a hand-off alongside another tool would be ambiguous).
    bound = model.bind_tools(TOOLS[agent], parallel_tool_calls=False)

    async def specialist(state: CallState, runtime: Runtime[CallContext]) -> dict:
        prompt = [SystemMessage(system_prompt(agent, state)), *view_for(agent, state["messages"])]
        try:
            full = None
            # A space between two agents' sentences in the same turn, so TTS doesn't glue them together.
            sep = " " if spoken_this_turn(state["messages"]) else ""
            async for chunk in bound.astream(prompt):
                if chunk.text:
                    runtime.stream_writer(sep + chunk.text)  # the ONLY path to the caller's ears
                    sep = ""
                full = chunk if full is None else full + chunk
            if full is None:
                raise RuntimeError("the model returned nothing")
            reply = AIMessage(content=full.content, tool_calls=full.tool_calls, id=full.id, name=agent)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("%s failed to produce a reply", agent)
            runtime.stream_writer(sep + FALLBACK_SPEECH)
            reply = AIMessage(content=FALLBACK_SPEECH, name=agent)
        return {"messages": [reply], "notes": []}

    specialist.__name__ = agent
    return specialist


def _tool_rounds(msgs: list[AnyMessage], agent: str) -> int:
    return sum(1 for m in _this_turn(msgs) if isinstance(m, AIMessage) and m.name == agent and m.tool_calls)


def route_after_specialist(agent: AgentName):
    def route(state: CallState) -> str:
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.tool_calls and _tool_rounds(state["messages"], agent) <= MAX_TOOL_ROUNDS:
            return f"{agent}_tools"
        return END

    route.__name__ = f"after_{agent}"
    return route


def route_after_tools(agent: AgentName):
    def route(state: CallState) -> str:
        if agent == "resolution" and state.get("email_pending") and state.get("verified"):
            return "confirmation_email"
        return state.get("active_agent", "greeter")

    route.__name__ = f"after_{agent}_tools"
    return route


def _tool_errors(e: Exception) -> str:
    if isinstance(e, ToolError):
        return str(e)
    logger.exception("tool failed", exc_info=e)
    return "That didn't work on my end. Apologise briefly and offer to connect them with a person if it keeps failing."


async def confirmation_email(state: CallState, runtime: Runtime[CallContext]) -> dict:
    """Plain code, no LLM: email the caller a confirmation of the action that was just completed.

    The email is built only from `last_action`, never from anything the model wrote, and it is
    sent at most once per action even if the caller interrupts.
    """
    ctx = runtime.context
    action = state.get("last_action")
    if not (state.get("verified") and action and state.get("email_pending")):
        return {"email_pending": False}
    key = (action["action"], action["ticket_id"])

    async def send() -> dict:
        customer = await run_db(db.get_customer, state["customer_id"])
        order = await run_db(db.get_order, state["order_id"])
        details = {
            "item": order["item_name"],
            "ticket_id": action.get("ticket_id"),
            "reason": action.get("reason"),
        }
        if action.get("new_date"):
            details["new_date"] = long_date(action["new_date"])
        return await ctx.send_email(customer["email"], state["order_id"], customer["name"], action["action"], details)

    if key not in ctx.emails:
        ctx.emails[key] = asyncio.ensure_future(send())
    try:
        result = await asyncio.shield(ctx.emails[key])
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("confirmation email failed")
        result = {"ok": False}

    if not result["ok"]:
        ctx.emails.pop(key, None)  # allow a later retry
        await report(ctx, state, "Email failed")
        return {"email_pending": False, "notes": [*(state.get("notes") or []), NOTE_EMAIL_FAILED]}
    await report(ctx, {**state, "email_sent": True}, "Email sent")
    return {"email_sent": True, "email_pending": False, "notes": [*(state.get("notes") or []), NOTE_EMAIL_SENT]}


# --------------------------------------------------------------------------- graph


def build_graph(model, checkpointer=None):
    """Compile the call graph. `model` is any LangChain chat model that supports bind_tools."""
    g = StateGraph(CallState, context_schema=CallContext)
    g.add_node("begin_turn", begin_turn)
    g.add_node("confirmation_email", confirmation_email)

    for agent in AGENTS:
        g.add_node(agent, make_specialist(agent, model))
        g.add_node(f"{agent}_tools", ToolNode(TOOLS[agent], name=f"{agent}_tools", handle_tool_errors=_tool_errors))
        g.add_conditional_edges(agent, route_after_specialist(agent), [f"{agent}_tools", END])
        after_tools = [agent, *HANDOFFS[agent]] + (["confirmation_email"] if agent == "resolution" else [])
        g.add_conditional_edges(f"{agent}_tools", route_after_tools(agent), after_tools)

    g.add_edge(START, "begin_turn")
    g.add_conditional_edges("begin_turn", route_after_begin, [*AGENTS, "confirmation_email"])
    g.add_edge("confirmation_email", "resolution")
    return g.compile(checkpointer=checkpointer)
