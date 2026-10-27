"""Publishes call state to the browser panel over the LiveKit data channel (topic "wismo.state")."""

import json
import logging

from .facts import describe_action
from .state import DISPLAY, CallContext

logger = logging.getLogger("wismo.panel")

STATE_TOPIC = "wismo.state"


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
        "notepad": notepad(state),
        "log": log,
    }


async def report(ctx: CallContext | None, state: dict, log: str | None = None) -> None:
    if ctx is None:
        return
    data = payload(state, log)
    if ctx.publish is not None:
        await ctx.publish(data)
        return
    room = ctx.room
    if room is None or not room.isconnected():
        return
    try:
        await room.local_participant.publish_data(json.dumps(data), topic=STATE_TOPIC)
    except Exception:
        logger.warning("failed to publish call state", exc_info=True)
