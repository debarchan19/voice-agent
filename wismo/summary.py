"""The after-call note: what happened, how the caller felt, and what happens next.

Facts come from code (the checkpointed call state and the per-call counters), the same way the
confirmation email is built only from `last_action`. The model only writes the prose: a short
summary, the caller's sentiment and the next steps.
"""

from __future__ import annotations

import logging
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from .facts import describe_action
from .state import CallContext

logger = logging.getLogger("wismo.summary")

Sentiment = Literal["positive", "neutral", "frustrated", "angry"]


class CallNote(BaseModel):
    """The model-written part of the after-call note."""

    summary: str = Field(description="Two short sentences, 40 words at most: why they called, and how the call ended.")
    sentiment: Sentiment = Field(description="How the caller felt by the END of the call.")
    sentiment_reason: str = Field(description="At most 12 words on why, e.g. 'relieved once the date was moved'.")
    next_steps: list[str] = Field(
        description="One to three concrete follow-ups, each under 14 words, saying who does what. "
        "Only steps that actually follow from the call."
    )


SYSTEM = """You write the after-call note for a delivery support line, for the human team that reads it later.
Use only what is in the transcript and the facts. Never invent ticket numbers, dates or promises.
If the caller tried to get past identity verification, mention it plainly in the summary."""


def facts(state: dict, ctx: CallContext | None) -> dict:
    """The parts of the note that come straight from code."""
    action = state.get("last_action")
    if not action:
        outcome = "No changes made"
    elif action["action"] == "escalation":
        outcome = "Escalated to a human"
    else:
        outcome = f"Resolved: {describe_action(action)}"
    return {
        "outcome": outcome,
        "order_id": state.get("order_id"),
        "customer": state.get("customer_name") if state.get("verified") else None,
        "verified": bool(state.get("verified")),
        "ticket_id": (action or {}).get("ticket_id"),
        "email_sent": bool(state.get("email_sent")),
        "failed_verifications": ctx.failed_verifications if ctx else 0,
        "gate_blocks": ctx.gate_blocks if ctx else 0,
    }


def _transcript(lines: list[tuple[str, str]]) -> str:
    return "\n".join(f"{'Caller' if role == 'user' else 'Agent'}: {text}" for role, text in lines if text.strip())


async def summarize_call(model, transcript: list[tuple[str, str]], state: dict, ctx: CallContext | None = None) -> dict:
    """`transcript` is (role, text) pairs, role "user" or "assistant". Never raises."""
    note = {"type": "summary", **facts(state, ctx), "turns": sum(1 for role, _ in transcript if role == "user")}
    if note["turns"] == 0:
        return {**note, "summary": "The caller hung up before saying anything.", "sentiment": "neutral",
                "sentiment_reason": "no conversation", "next_steps": []}
    fact_lines = "\n".join(f"{k}: {v}" for k, v in note.items() if k != "type")
    try:
        written: CallNote = await model.with_structured_output(CallNote).ainvoke(
            [SystemMessage(SYSTEM), HumanMessage(f"Facts from the system:\n{fact_lines}\n\nTranscript:\n{_transcript(transcript)}")]
        )
        return {**note, **written.model_dump(), "next_steps": written.next_steps[:3]}
    except Exception:
        logger.exception("call summary failed")
        return {**note, "summary": "The summary couldn't be written this time.", "sentiment": "neutral",
                "sentiment_reason": "unavailable", "next_steps": []}
