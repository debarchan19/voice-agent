"""Publishes call state to the browser over the LiveKit data channel.

Two topics:
  * "wismo.state": the call panel (agent, customer, order, notepad, activity log line)
  * "wismo.trace": the live graph run (node, model and tool spans), voice latency per reply,
    verification-gate blocks. See wismo/trace.py.
"""

import json
import logging

from .facts import describe_action
from .prompts import MAX_VERIFY_ATTEMPTS
from .state import DISPLAY, CallContext

logger = logging.getLogger("wismo.panel")

STATE_TOPIC = "wismo.state"
TRACE_TOPIC = "wismo.trace"


def notepad(state: dict) -> dict:
    """The call data the panel shows, with personal details hidden until verified."""
    verified = bool(state.get("verified"))
    action = state.get("last_action")
    return {
        "current_agent": DISPLAY[state.get("active_agent", "greeter")],
        "order_id": state.get("order_id") or "—",
        "verified": "yes" if verified else "no",
        "customer_name": (state.get("customer_name") or "—") if verified else "—",
        "issue_summary": state.get("issue_summary") or "—",
        "last_action": describe_action(action) if action else "—",
    }


def payload(state: dict, log: str | None = None) -> dict:
    verified = bool(state.get("verified"))
    return {
        "type": "state",
        "agent": DISPLAY[state.get("active_agent", "greeter")],
        "verified": verified,
        "customer": state.get("customer_name") if verified else None,
        "order_id": state.get("order_id"),
        # Order details only reach the screen once the caller is verified, same as the voice.
        "status": state.get("order_status") if verified else None,
        "promised_date": state.get("promised_date") if verified else None,
        "verify_attempts": state.get("verify_attempts", 0),
        "max_verify_attempts": MAX_VERIFY_ATTEMPTS,
        "notepad": notepad(state),
        "log": log,
    }


def voice_turn(role: str, metrics: dict, interrupted: bool, at_ms: float) -> dict:
    """Latency of one spoken turn, from LiveKit's per-message metrics (seconds in, ms out)."""

    def ms(key: str) -> int | None:
        value = metrics.get(key)
        return round(value * 1000) if isinstance(value, (int, float)) and value >= 0 else None

    if role == "user":
        return {"type": "voice", "role": "user", "at": at_ms,
                "end_of_turn": ms("end_of_turn_delay"), "transcript": ms("transcription_delay")}
    return {"type": "voice", "role": "agent", "at": at_ms, "interrupted": interrupted,
            "first_token": ms("llm_node_ttft"), "first_audio": ms("tts_node_ttfb"), "total": ms("e2e_latency")}


async def send(ctx: CallContext | None, data: dict, topic: str = STATE_TOPIC) -> None:
    if ctx is None:
        return
    if ctx.publish is not None:
        await ctx.publish(data)
        return
    room = ctx.room
    if room is None or not room.isconnected():
        return
    try:
        await room.local_participant.publish_data(json.dumps(data), topic=topic)
    except Exception:
        logger.warning("failed to publish to %s", topic, exc_info=True)


async def report(ctx: CallContext | None, state: dict, log: str | None = None) -> None:
    await send(ctx, payload(state, log))
