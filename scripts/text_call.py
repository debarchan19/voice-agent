"""A real end-to-end call without audio: the real model, real LLMAdapter, real graph, temp database.

It plays the caller's side as text, prints what the agent would say, and checks the things that
are easy to get wrong in voice: no tool text spoken, verification digits never echoed, hand-offs
in the same turn, one email. The email is recorded, not sent, unless you pass --send-email.

Usage: python scripts/text_call.py [--send-email]
"""

import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
os.environ["SHOP_DB"] = os.path.join(tempfile.mkdtemp(), "shop.db")

import db  # noqa: E402
import email_tool  # noqa: E402
import seed  # noqa: E402
from fakes import FakeLiveKit  # noqa: E402
from langchain_anthropic import ChatAnthropic  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402

from wismo import CallContext, build_graph  # noqa: E402

CALLER = [
    "Hi, my espresso machine is really late. The order number is O R D 4 8 2 1 3.",
    "Yes, that's right.",
    "0 1 4 2",
    "Why is it taking so long?",
    "Can you move the delivery to this Friday instead?",
    "Yes, please go ahead.",
]


class CountingModel:
    """Wraps the real model and records how many model calls each caller turn needed."""

    def __init__(self, model):
        self.model, self.calls = model, []

    def bind_tools(self, tools, **kwargs):
        bound, outer = self.model.bind_tools(tools, **kwargs), self

        class Wrapped:
            async def astream(self, messages):
                start, first = time.perf_counter(), None
                async for chunk in bound.astream(messages):
                    if first is None and chunk.text:
                        first = time.perf_counter() - start
                    yield chunk
                outer.calls.append(first)

        return Wrapped()


async def main(send_email: bool) -> int:
    seed.seed(os.environ["SHOP_DB"])
    panel, emails = [], []

    async def publish(payload):
        panel.append(payload)

    async def fake_email(*args):
        emails.append(args)
        return {"ok": True, "to": args[0]}

    model = CountingModel(ChatAnthropic(model="claude-sonnet-4-6", max_tokens=400))
    ctx = CallContext(publish=publish, send_email=email_tool.send_confirmation_email if send_email else fake_email)
    graph = build_graph(model, checkpointer=InMemorySaver())
    phone = FakeLiveKit(graph, ctx)
    print(f"\nAGENT: {phone.chat_ctx.messages()[-1].text_content}")

    per_turn, spoken_all = [], []
    for line in CALLER:
        before = len(model.calls)
        print(f"\nCALLER: {line}")
        spoken = await phone.turn(line)
        spoken_all.append(spoken)
        per_turn.append(len(model.calls) - before)
        print(f"AGENT:  {spoken}")
        firsts = [f"{t:.1f}s" if t else "tool call" for t in model.calls[before:]]
        print(f"        [{per_turn[-1]} model call(s); first words: {', '.join(firsts)}]")

    state = (await graph.aget_state({"configurable": {"thread_id": "room-1"}})).values
    heard = " ".join(spoken_all)
    checks = {
        "digits never echoed back": "0142" not in heard.replace(" ", "") and "0 1 4 2" not in heard,
        "no tool or note text spoken": not any(w in heard for w in ("Transferred", "ticket", "tool", "Verified.")),
        "verified": state.get("verified") is True,
        "rescheduled": state.get("last_action", {}).get("action") == "reschedule",
        "email sent once": state.get("email_sent") is True and (send_email or len(emails) == 1),
        "ended on Resolution": state.get("active_agent") == "resolution",
    }
    print("\nPANEL LOG:", [p["log"] for p in panel if p["log"]])
    print("MODEL CALLS PER TURN:", per_turn)
    print()
    for name, ok in checks.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    conn = db.connect()
    print("\nTICKETS:", [tuple(r) for r in conn.execute("SELECT id, order_id, type FROM support_tickets WHERE id > 1001")])
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main("--send-email" in sys.argv)))
