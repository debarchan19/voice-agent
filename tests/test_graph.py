"""Tests for the LangGraph brain, driven through the real LLMAdapter with a scripted fake model.

No network and no LiveKit server: `FakeLiveKit` feeds the adapter exactly what LiveKit would
(a full transcript every turn, with LiveKit's own message ids), and `ScriptedModel` plays back
the model's replies. This is what lets routing, hand-offs, the gate and barge-in be unit tested.
"""

import asyncio
import time
from datetime import date, timedelta
from pathlib import Path

import pytest
from fakes import FakeLiveKit, ScriptedModel, call, say
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

import db
import seed
from wismo import CallContext, build_graph
from wismo.state import AGENTS

ORDER = "ORD-48213"  # Maya Patel, delayed (weather hold); verify with 0142
FRIDAY = (date.today() + timedelta(days=3)).isoformat()


@pytest.fixture
def shop(tmp_path, monkeypatch):
    path = str(tmp_path / "shop.db")
    seed.seed(path)
    monkeypatch.setattr(db, "DB_PATH", path)
    return path


class Call:
    """One scripted call: graph + fake LiveKit + captured panel messages and emails."""

    def __init__(self, script, send_delay: float = 0.0, token_delay: float = 0.0):
        self.model = ScriptedModel(script, token_delay=token_delay)
        self.panel: list[dict] = []
        self.emails: list[tuple] = []
        self.send_delay = send_delay

        async def publish(payload):
            self.panel.append(payload)

        async def send_email(customer_email, order_id, customer_name, action, details):
            await asyncio.sleep(self.send_delay)
            self.emails.append((customer_email, order_id, customer_name, action, details))
            return {"ok": True, "to": customer_email}

        self.ctx = CallContext(publish=publish, send_email=send_email)
        self.graph = build_graph(self.model, checkpointer=InMemorySaver())
        self.phone = FakeLiveKit(self.graph, self.ctx)
        self.config = {"configurable": {"thread_id": "room-1"}}

    async def say(self, text: str, **kw) -> str:
        return await self.phone.turn(text, **kw)

    async def state(self) -> dict:
        return (await self.graph.aget_state(self.config)).values

    @property
    def logs(self) -> list[str]:
        return [p["log"] for p in self.panel if p["log"]]

    def agents_called(self) -> list[str]:
        return [c["agent"] for c in self.model.calls]


def hand_to_order_status(order=ORDER):
    return [("greeter", call("transfer_to_order_status", "Let me pull that up.", order_id=order)),
            ("order_status", say("Could you give me the last four digits of the phone number?"))]


def verify(order=ORDER, digits="0142"):
    return [("order_status", call("verify_customer", order_id=order, last_four_phone_digits=digits)),
            ("order_status", say("Thanks Maya, your espresso machine is delayed by a weather hold."))]


def to_resolution():
    return [("order_status", call("transfer_to_resolution", "Of course.", issue_summary="Move delivery to Friday")),
            ("resolution", say("Shall I move it to this Friday?"))]


def reschedule(order=ORDER):
    return [("resolution", call("reschedule_delivery", order_id=order, new_date=FRIDAY)),
            ("resolution", say("All done, your delivery is moved and a confirmation email is on its way."))]


# --------------------------------------------------------------------------- topology


def test_graph_topology_matches_the_diagram(shop):
    graph = build_graph(ScriptedModel([]))
    edges = {(e.source, e.target) for e in graph.get_graph().edges}
    for agent in AGENTS:
        assert (agent, f"{agent}_tools") in edges and (agent, "__end__") in edges
        assert (f"{agent}_tools", agent) in edges
    assert ("greeter_tools", "order_status") in edges
    assert ("order_status_tools", "resolution") in edges
    assert ("resolution_tools", "order_status") in edges
    assert ("resolution_tools", "confirmation_email") in edges
    assert ("confirmation_email", "resolution") in edges
    # A greeter can't jump straight to Resolution: there is no such edge.
    assert ("greeter_tools", "resolution") not in edges and ("greeter", "resolution") not in edges
    diagram = Path(__file__).resolve().parent.parent / "docs" / "graph.mmd"
    assert diagram.read_text().strip() == graph.get_graph().draw_mermaid().strip(), "run: python scripts/draw_graph.py"


def test_parallel_tool_calls_are_disabled(shop):
    call_ = Call([])
    assert len(call_.model.bind_kwargs) == 3
    assert all(kw == {"parallel_tool_calls": False} for kw in call_.model.bind_kwargs)


# --------------------------------------------------------------------------- speech


def test_only_model_text_is_spoken(shop):
    async def go():
        c = Call(hand_to_order_status())
        spoken = await c.say("It's order O R D 4 8 2 1 3.")
        # Both agents' sentences, with a space between them. No tool results, notes or routing text.
        assert spoken == "Let me pull that up. Could you give me the last four digits of the phone number?"
        assert "Transferred" not in spoken and "exists" not in spoken
    asyncio.run(go())


def test_handoff_replies_in_the_same_turn(shop):
    async def go():
        c = Call(hand_to_order_status())
        await c.say("O R D 4 8 2 1 3")
        assert c.agents_called() == ["greeter", "order_status"]  # 2 model calls, one caller turn
        assert (await c.state())["active_agent"] == "order_status"
        assert c.logs == ["Captured order ORD-48213", "Handed off to Order Status"]
    asyncio.run(go())


def test_unknown_order_does_not_hand_off(shop):
    async def go():
        c = Call([("greeter", call("transfer_to_order_status", order_id="ORD-00000")),
                  ("greeter", say("I couldn't find that one. Could you read it again?"))])
        await c.say("O R D 0 0 0 0 0")
        assert c.agents_called() == ["greeter", "greeter"]
        assert (await c.state()).get("active_agent", "greeter") == "greeter"
    asyncio.run(go())


def test_model_failure_speaks_a_fallback(shop):
    async def go():
        c = Call([("greeter", RuntimeError("boom"))])
        assert "trouble on my end" in await c.say("hello")
    asyncio.run(go())


# --------------------------------------------------------------------------- persistence


def test_five_turn_call_keeps_state_and_never_duplicates_replies(shop):
    async def go():
        c = Call([
            *hand_to_order_status(),
            *verify(),
            ("order_status", say("It's stuck at the Denver hub because of the storm.")),
            *to_resolution(),
            *reschedule(),
        ])
        await c.say("My order is O R D 4 8 2 1 3.")
        await c.say("0 1 4 2")
        await c.say("Why is it so late?")
        await c.say("Can you move it to Friday?")
        await c.say("Yes please.")

        state = await c.state()
        assert state["active_agent"] == "resolution" and state["verified"] is True
        assert state["customer_name"] == "Maya Patel" and state["promised_date"] == FRIDAY
        assert state["last_action"]["action"] == "reschedule" and state["email_sent"] is True

        # Every prompt the model saw: no duplicated assistant text, no system message from LiveKit,
        # and every tool call has its result.
        for seen in c.model.calls:
            msgs = seen["messages"]
            assert isinstance(msgs[0], SystemMessage) and not any(isinstance(m, SystemMessage) for m in msgs[1:])
            texts = [m.text for m in msgs if isinstance(m, AIMessage) and m.text]
            assert len(texts) == len(set(texts)), texts
            answered = {m.tool_call_id for m in msgs if isinstance(m, ToolMessage)}
            assert all(tc["id"] in answered for m in msgs if isinstance(m, AIMessage) for tc in m.tool_calls)
    asyncio.run(go())


# --------------------------------------------------------------------------- the gate


def test_unverified_caller_cannot_reach_tracking_or_resolution(shop):
    async def go():
        c = Call([
            *hand_to_order_status(),
            ("order_status", call("get_tracking_events", order_id=ORDER)),
            ("order_status", call("transfer_to_resolution", issue_summary="refund")),
            ("order_status", say("I need to verify you first. What are the last four digits?")),
        ])
        await c.say("O R D 4 8 2 1 3")
        spoken = await c.say("Where is it, and I want a refund.")
        assert "verify" in spoken
        state = await c.state()
        assert state["active_agent"] == "order_status" and not state.get("verified")
        errors = [m for m in state["messages"] if isinstance(m, ToolMessage) and m.status == "error"]
        assert len(errors) == 2 and all("isn't verified" in m.content for m in errors)
        # The panel never showed order details to an unverified caller.
        assert all(p["status"] is None and p["customer"] is None for p in c.panel)
    asyncio.run(go())


def test_unverified_caller_can_still_escalate(shop):
    async def go():
        c = Call([*hand_to_order_status(),
                  ("order_status", call("escalate_to_human", reason="Caller wants a person")),
                  ("order_status", say("A specialist will call you back."))])
        await c.say("O R D 4 8 2 1 3")
        await c.say("Let me talk to a human.")
        conn = db.connect()
        row = conn.execute("SELECT order_id, notes FROM support_tickets WHERE type='escalation'").fetchone()
        conn.close()
        assert row["order_id"] is None and "unverified" in row["notes"]
        assert c.emails == []
    asyncio.run(go())


def test_a_tool_from_another_agent_is_unreachable(shop):
    async def go():
        c = Call([*hand_to_order_status(),
                  ("order_status", call("request_refund", order_id=ORDER, reason="late")),
                  ("order_status", say("I can't do that yet."))])
        await c.say("O R D 4 8 2 1 3")
        await c.say("Refund me.")
        conn = db.connect()
        assert conn.execute("SELECT COUNT(*) FROM support_tickets WHERE type='refund'").fetchone()[0] == 0
        conn.close()
        errors = [m for m in (await c.state())["messages"] if isinstance(m, ToolMessage) and m.status == "error"]
        assert errors and "not a valid tool" in errors[0].content
    asyncio.run(go())


def test_verification_attempts_are_capped_across_turns(shop):
    async def go():
        script = hand_to_order_status()
        for digits in ("1111", "2222", "3333"):
            script += [("order_status", call("verify_customer", order_id=ORDER, last_four_phone_digits=digits)),
                       ("order_status", say("Those don't match."))]
        script += [("order_status", call("verify_customer", order_id=ORDER, last_four_phone_digits="0142")),
                   ("order_status", say("I can't try again. Shall I get a person to call you?"))]
        c = Call(script)
        await c.say("O R D 4 8 2 1 3")
        for digits in ("1 1 1 1", "2 2 2 2", "3 3 3 3", "0 1 4 2"):
            await c.say(digits)
        state = await c.state()
        assert not state.get("verified") and state["verify_attempts"] == 3  # the right digits were refused
    asyncio.run(go())


# --------------------------------------------------------------------------- action and email


def test_action_sends_one_email_built_from_the_action(shop):
    async def go():
        c = Call([*hand_to_order_status(), *verify(), *to_resolution(), *reschedule()])
        for text in ("O R D 4 8 2 1 3", "0 1 4 2", "Move it to Friday", "Yes please"):
            await c.say(text)
        # The last turn: reschedule tool, then the email node (code), then the reply = 2 model calls.
        assert c.agents_called()[-2:] == ["resolution", "resolution"]
        assert len(c.emails) == 1
        email, order_id, name, action, details = c.emails[0]
        assert (email, order_id, name, action) == ("maya@example.com", ORDER, "Maya Patel", "reschedule")
        assert details["new_date"].startswith(f"{date.fromisoformat(FRIDAY):%A}") and details["ticket_id"]
        friday = date.fromisoformat(FRIDAY)
        assert f"Rescheduled delivery to {friday:%a, %b} {friday.day}" in c.logs
        assert "Email sent" in c.logs
    asyncio.run(go())


def test_barge_in_during_a_slow_email_sends_it_exactly_once(shop):
    async def go():
        c = Call([*hand_to_order_status(), *verify(), *to_resolution(),
                  ("resolution", call("reschedule_delivery", order_id=ORDER, new_date=FRIDAY)),
                  ("resolution", say("Done, and the email is on its way.")),
                  ("resolution", say("You're welcome."))], send_delay=0.4)
        for text in ("O R D 4 8 2 1 3", "0 1 4 2", "Move it to Friday"):
            await c.say(text)
        await c.say("Yes please", barge_in_after_s=0.15)  # the caller cuts in while the email is sending
        await c.say("Thanks!")
        state = await c.state()
        assert len(c.emails) == 1 and state["email_sent"] is True and state["email_pending"] is False
        conn = db.connect()
        assert conn.execute("SELECT COUNT(*) FROM support_tickets WHERE type='reschedule'").fetchone()[0] == 1
        conn.close()
    asyncio.run(go())


def test_barge_in_during_a_slow_refund_then_retry_makes_one_ticket(shop, monkeypatch):
    real = db.request_refund

    def slow_refund(conn, order_id, reason):
        time.sleep(0.4)
        return real(conn, order_id, reason)

    monkeypatch.setattr(db, "request_refund", slow_refund)

    async def go():
        refund = ("resolution", call("request_refund", order_id=ORDER, reason="Too late"))
        c = Call([*hand_to_order_status(), *verify(), *to_resolution(),
                  refund, refund,  # the model asks again after the interruption
                  ("resolution", say("Your refund request is open and the email is on its way."))])
        for text in ("O R D 4 8 2 1 3", "0 1 4 2", "I want a refund"):
            await c.say(text)
        await c.say("Yes, refund it", barge_in_after_s=0.15)  # cut in while the ticket is being written
        await c.say("Sorry, did that go through?")
        conn = db.connect()
        assert conn.execute("SELECT COUNT(*) FROM support_tickets WHERE type='refund'").fetchone()[0] == 1
        conn.close()
        assert len(c.emails) == 1
    asyncio.run(go())


def test_barge_in_after_a_handoff_keeps_the_handoff(shop):
    async def go():
        c = Call([("greeter", call("transfer_to_order_status", "Sure.", order_id=ORDER)),
                  ("order_status", say("Could you give me the last four digits of the phone number on the order?")),
                  ("order_status", say("Of course, go ahead."))], token_delay=0.01)
        await c.say("O R D 4 8 2 1 3", barge_in_after_chars=30)  # interrupted while Order Status is talking
        state = await c.state()
        assert state["active_agent"] == "order_status" and state["order_id"] == ORDER
        await c.say("Sorry, one second.")
        assert c.agents_called() == ["greeter", "order_status", "order_status"]  # greeter isn't asked again
    asyncio.run(go())


# --------------------------------------------------------------------------- limits and panel


def test_tool_round_cap_ends_the_turn_and_the_next_turn_recovers(shop):
    async def go():
        script = [("greeter", call("escalate_to_human", reason="loop")) for _ in range(5)]
        script += [("greeter", say("Sorry about that. How can I help?"))]
        c = Call(script)
        await c.say("hello")  # five tool rounds, then the cap ends the turn
        await c.say("hello again")
        last_prompt = c.model.calls[-1]["messages"]
        answered = {m.tool_call_id for m in last_prompt if isinstance(m, ToolMessage)}
        assert all(tc["id"] in answered for m in last_prompt if isinstance(m, AIMessage) for tc in m.tool_calls)
    asyncio.run(go())


def test_panel_payload_matches_what_the_browser_expects(shop):
    async def go():
        c = Call([*hand_to_order_status(), *verify(), *to_resolution(), *reschedule()])
        for text in ("O R D 4 8 2 1 3", "0 1 4 2", "Move it to Friday", "Yes please"):
            await c.say(text)
        expected_keys = {"type", "agent", "verified", "customer", "order_id", "status", "promised_date", "notepad", "log"}
        assert all(set(p) == expected_keys and p["type"] == "state" for p in c.panel)
        assert set(c.panel[-1]["notepad"]) == {
            "current_agent", "order_id", "verified", "customer_name", "issue_summary", "last_action"}
        assert [p["agent"] for p in c.panel][-1] == "Resolution"
        for expected in ("Captured order ORD-48213", "Handed off to Order Status", "Verification passed",
                         "Handed off to Resolution", "Email sent"):
            assert expected in c.logs
        assert c.logs.index("Verification passed") < c.logs.index("Handed off to Resolution") < c.logs.index("Email sent")
        last = c.panel[-1]
        assert last["verified"] and last["customer"] == "Maya Patel" and last["status"] == "delayed"
    asyncio.run(go())
