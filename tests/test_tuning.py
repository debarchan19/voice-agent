"""Backend-specific fixes for the self-hosted model (wismo/tuning.py). No network.

The most important property: Claude's prompts and tool schemas are exactly what they were before
any fix existed, whatever LOCAL_LLM_FIXES says.
"""

import asyncio
import hashlib
import re

import pytest
from fakes import FakeLiveKit, ScriptedModel, call, say
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

import db
import seed
from wismo import CallContext, build_graph
from wismo.graph import summary, system_prompt, unbacked_claim
from wismo.prompts import GUARD_FALLBACK_SPEECH, ROLES, voice_rules
from wismo.tool_specs import tool_specs
from wismo.tools import TOOLS
from wismo.tuning import FIXES, LOCAL_DEFAULT_FIXES, NO_TUNING, Tuning, parse_fixes, tuning_for

ALL = Tuning(frozenset(FIXES))


def _rules_without_date() -> str:
    return re.sub(r"Today is .*\n", "", voice_rules())


# sha256 of the shared prompt text (date line removed) at commit def521e, before wismo/tuning.py existed.
# If this fails, Claude's prompt changed: that must be a deliberate decision, not a side effect of a Qwen fix.
PROMPT_SHA256_BEFORE_FIXES = "9fbf1fd9d381c4a95ac06dbdc3c38f059ac442973cfe65e1892cee99959da73c"


@pytest.fixture
def shop(tmp_path, monkeypatch):
    path = str(tmp_path / "shop.db")
    seed.seed(path)
    monkeypatch.setattr(db, "DB_PATH", path)
    return path


def test_claude_never_gets_fixes(monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_FIXES", ",".join(FIXES))
    assert tuning_for("anthropic") is NO_TUNING


def test_local_fix_selection(monkeypatch):
    monkeypatch.delenv("LOCAL_LLM_FIXES", raising=False)
    assert tuning_for("local").fixes == LOCAL_DEFAULT_FIXES
    monkeypatch.setenv("LOCAL_LLM_FIXES", "none")
    assert tuning_for("local") == NO_TUNING
    monkeypatch.setenv("LOCAL_LLM_FIXES", "act_first, few_shot")
    assert tuning_for("local").fixes == {"act_first", "few_shot"}
    assert parse_fixes("default+act_first").fixes == LOCAL_DEFAULT_FIXES | {"act_first"}
    with pytest.raises(ValueError):
        parse_fixes("act_first,made_up")


@pytest.mark.parametrize("agent", list(ROLES))
def test_untuned_prompt_is_the_original(agent):
    state = {"messages": [HumanMessage("hi")], "order_id": "ORD-51907", "notes": ["A note."]}
    original = (f"{voice_rules()}\n\n{ROLES[agent]}\n\nContext from earlier in this call: {summary(state)}"
                "\n\nYou have just taken over the call, or something just happened. A note.")
    assert system_prompt(agent, state) == original
    assert system_prompt(agent, state, NO_TUNING) == original


def test_shared_prompt_text_is_pinned():
    digest = hashlib.sha256((_rules_without_date() + "".join(ROLES.values())).encode()).hexdigest()
    assert digest == PROMPT_SHA256_BEFORE_FIXES


def test_tuned_prompt_adds_only_the_selected_rules():
    state = {"messages": [HumanMessage("hi")]}
    base = system_prompt("resolution", state)
    one = system_prompt("resolution", state, Tuning(frozenset({"act_first"})))
    assert one.startswith(voice_rules()) and one.endswith(base[len(voice_rules()):])
    assert "in this same reply" in one and "None, null" not in one
    shot = system_prompt("resolution", state, Tuning(frozenset({"few_shot"})))
    assert "ORD-70315" in shot and "How you use tools" not in shot
    assert "ORD-70315" not in system_prompt("order_status", state, ALL)  # no example for order_status


@pytest.mark.parametrize("agent", list(TOOLS))
def test_untuned_tool_schemas_are_the_tool_objects(agent):
    assert tool_specs(agent, NO_TUNING) is TOOLS[agent]
    assert tool_specs(agent, Tuning(frozenset({"act_first", "narration_guard"}))) is TOOLS[agent]


def test_qwen_tool_docs_keep_names_and_arguments():
    for agent, tools in TOOLS.items():
        specs = tool_specs(agent, Tuning(frozenset({"qwen_tool_docs"})))
        for t, spec in zip(tools, specs):
            fn = spec["function"]
            assert fn["name"] == t.name
            assert set(fn["parameters"]["properties"]) == set(t.args)
            assert all(p.get("description") for p in fn["parameters"]["properties"].values())
            assert "Args:" not in fn["description"]


def test_plain_optional_args_drop_the_null_type():
    spec = tool_specs("greeter", Tuning(frozenset({"plain_optional_args"})))[0]
    props = spec["function"]["parameters"]["properties"]
    assert spec["function"]["name"] == "transfer_to_order_status"
    assert props["order_id"]["type"] == props["phone"]["type"] == "string"
    assert "anyOf" not in props["order_id"] and "default" not in props["order_id"]
    assert not spec["function"]["parameters"].get("required")
    # required arguments elsewhere are untouched
    ticket = next(s for s in tool_specs("resolution", Tuning(frozenset({"plain_optional_args"})))
                  if s["function"]["name"] == "create_ticket")
    assert set(ticket["function"]["parameters"]["required"]) == {"order_id", "type", "notes"}


# --------------------------------------------------------------------------- narration guard detector


def _state(**kw):
    return {"messages": [HumanMessage("yes please")], **kw}


@pytest.mark.parametrize("agent, text", [
    ("resolution", "One moment. I'm opening a lost package ticket for order ORD-12345 now."),
    ("resolution", "One moment. I've opened the support ticket for you."),
    ("resolution", "Done. Your delivery is now booked for Friday."),
    ("resolution", "I'm processing the refund now."),
    ("greeter", "Okay, let me check that for you. One moment."),
    ("greeter", "One moment. I'll pull up your account now."),
    ("order_status", "One moment."),
])
def test_guard_flags_claims_without_a_tool(agent, text):
    assert unbacked_claim(agent, text, _state())


@pytest.mark.parametrize("agent, text", [
    ("resolution", "I can open a lost package ticket so the team can look into it. Shall I do that?"),
    ("resolution", "I'll move it to this Friday, the twentieth. Is that okay?"),
    ("resolution", "Would you like me to request a refund instead?"),
    ("greeter", "Got it. That's 7 2 0, 5 5 5, 0 1 4 2, right?"),
    ("order_status", "Thanks, James. Your headphones are running late. What would you like to do?"),
    ("greeter", "I can only help with deliveries, I'm afraid."),
])
def test_guard_ignores_offers_questions_and_plain_talk(agent, text):
    assert unbacked_claim(agent, text, _state()) is None


def test_guard_accepts_claims_a_tool_made_true():
    ran = _state()
    ran["messages"] = [HumanMessage("yes"), AIMessage("", name="resolution", tool_calls=[
        {"name": "create_ticket", "args": {}, "id": "c1"}])]
    assert unbacked_claim("resolution", "I've opened the ticket for you.", ran) is None
    earlier = _state(last_action={"action": "reschedule", "ticket_id": 1001})
    assert unbacked_claim("resolution", "Your delivery has been rescheduled, all done.", earlier) is None


# --------------------------------------------------------------------------- narration guard in the graph

GUARDED = Tuning(frozenset({"narration_guard"}))


def _guarded_call(script, tuning=GUARDED):
    model = ScriptedModel(script)
    graph = build_graph(model, checkpointer=InMemorySaver(), tuning=tuning)
    events = []

    async def publish(p):
        events.append(p)

    async def fake_email(*a):
        return {"ok": True}

    ctx = CallContext(publish=publish, send_email=fake_email)
    return model, graph, ctx, events


async def _to_resolution(phone, verified=True):
    await phone.turn("My order is O R D 6 0 5 8 2.")
    await phone.turn("Yes.")
    if verified:
        await phone.turn("0 1 1 9.")
        await phone.turn("It never arrived.")


OPENING = [
    ("greeter", say("That's O R D, 6 0 5 8 2, right?")),
    ("greeter", call("transfer_to_order_status", order_id="ORD-60582")),
    ("order_status", say("Last four digits, please?")),
    ("order_status", call("verify_customer", order_id="ORD-60582", last_four_phone_digits="0119")),
    ("order_status", say("Thanks, Aisha. It shows delivered.")),
    ("order_status", call("transfer_to_resolution", issue_summary="Lost package.")),
    ("resolution", say("Sorry about that. Shall I open a lost package ticket?")),
]


def test_guard_retries_once_and_the_tool_runs(shop):
    async def go():
        script = OPENING + [
            ("resolution", say("One moment. I'm opening the ticket now.")),  # narration, no tool call
            ("resolution", call("create_ticket", order_id="ORD-60582", type="lost_package", notes="Never arrived.")),
            ("resolution", say("Ticket 1003 is open.")),
        ]
        model, graph, ctx, events = _guarded_call(script)
        phone = FakeLiveKit(graph, ctx)
        await _to_resolution(phone)
        spoken = await phone.turn("Yes please.")
        assert spoken.startswith("One moment. I'm opening the ticket now.") and "Ticket 1003" in spoken
        assert not model.script
        guard = [e for e in events if e.get("type") == "guard"]
        assert len(guard) == 1 and guard[0]["outcome"] == "tool_call" and guard[0]["tools"] == ["create_ticket"]
        assert "Correction:" in model.calls[-2]["messages"][0].content  # the retry saw the corrective note
        state = (await graph.aget_state({"configurable": {"thread_id": "room-1"}})).values
        assert state["last_action"]["action"] == "ticket"

    asyncio.run(go())


def test_guard_falls_back_honestly_when_the_retry_narrates_again(shop):
    async def go():
        script = OPENING + [
            ("resolution", say("One moment. I'm opening the ticket now.")),
            ("resolution", say("I'm opening it right now.")),  # still no tool call: not spoken
        ]
        model, graph, ctx, events = _guarded_call(script)
        phone = FakeLiveKit(graph, ctx)
        await _to_resolution(phone)
        spoken = await phone.turn("Yes please.")
        assert spoken == f"One moment. I'm opening the ticket now. {GUARD_FALLBACK_SPEECH}"
        assert [e["outcome"] for e in events if e.get("type") == "guard"] == ["fallback"]

    asyncio.run(go())


def test_guard_retry_cannot_get_past_the_verification_gate(shop):
    async def go():
        # Unverified caller at Order Status; the model narrates, the retry tries a gated tool: the gate refuses it.
        script = OPENING[:3] + [
            ("order_status", say("One moment, I'm checking the tracking now.")),
            ("order_status", call("get_tracking_events", order_id="ORD-60582")),
            ("order_status", say("I need to verify you first. What are the last four digits?")),
        ]
        model, graph, ctx, events = _guarded_call(script)
        phone = FakeLiveKit(graph, ctx)
        await _to_resolution(phone, verified=False)
        spoken = await phone.turn("Where is it?")
        assert "verify you first" in spoken
        state = (await graph.aget_state({"configurable": {"thread_id": "room-1"}})).values
        results = [m for m in state["messages"] if m.type == "tool" and m.name == "get_tracking_events"]
        assert results and "isn't verified" in results[-1].content and not state.get("verified")

    asyncio.run(go())


def test_no_guard_without_the_fix(shop):
    async def go():
        script = OPENING + [("resolution", say("One moment. I'm opening the ticket now."))]
        model, graph, ctx, events = _guarded_call(script, tuning=NO_TUNING)
        phone = FakeLiveKit(graph, ctx)
        await _to_resolution(phone)
        assert await phone.turn("Yes please.") == "One moment. I'm opening the ticket now."
        assert not [e for e in events if e.get("type") == "guard"] and not model.script

    asyncio.run(go())
