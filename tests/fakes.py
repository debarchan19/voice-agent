"""Test doubles: a scripted chat model, a fake LiveKit turn loop, and a single-tool runner.

None of this touches the network. The fake model plays back a script of replies (text, then
tool calls), and the fake LiveKit loop feeds the *real* LLMAdapter exactly what LiveKit would.
"""

import asyncio
import itertools
import json

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.messages.tool import tool_call_chunk
from langgraph.graph import START, StateGraph
from langgraph.prebuilt import ToolNode

from livekit.agents.llm import ChatContext
from livekit.agents.utils import shortuuid
from livekit.plugins.langchain import LLMAdapter

from wismo.graph import _tool_errors
from wismo.state import CallContext, CallState
from wismo.tools import TOOLS

GREETING = "Hi, thanks for calling order support. What's your order number?"


def say(text: str) -> AIMessage:
    return AIMessage(content=text)


_ids = itertools.count(1)


def call(name: str, text: str = "", **args) -> AIMessage:
    return AIMessage(content=text, tool_calls=[{"name": name, "args": args, "id": f"call_{next(_ids)}"}])


def agent_of(tools) -> str:
    names = {t.name for t in tools}
    if "reschedule_delivery" in names:
        return "resolution"
    if "verify_customer" in names:
        return "order_status"
    return "greeter"


class ScriptedModel:
    """Stands in for ChatAnthropic. `script` is a list of (expected_agent, reply) consumed in order."""

    def __init__(self, script, token_delay: float = 0.0):
        self.script = list(script)
        self.token_delay = token_delay
        self.calls: list[dict] = []  # what each model call saw
        self.bind_kwargs: list[dict] = []

    def bind_tools(self, tools, **kwargs):
        self.bind_kwargs.append(kwargs)
        return _Bound(self, agent_of(tools))


class _Bound:
    def __init__(self, model: ScriptedModel, agent: str):
        self.model, self.agent = model, agent

    async def astream(self, messages: list[BaseMessage]):
        m = self.model
        m.calls.append({"agent": self.agent, "messages": messages})
        assert m.script, f"script exhausted; {self.agent} was called"
        want, reply = m.script.pop(0)
        assert want == self.agent, f"expected {want} to be called, got {self.agent}"
        if isinstance(reply, Exception):
            raise reply
        words = reply.content.split(" ") if reply.content else []
        for i, w in enumerate(words):
            if m.token_delay:
                await asyncio.sleep(m.token_delay)
            yield AIMessageChunk(content=w if i == 0 else " " + w)
        for j, tc in enumerate(reply.tool_calls):
            yield AIMessageChunk(
                content="",
                tool_call_chunks=[tool_call_chunk(name=tc["name"], args=json.dumps(tc["args"]), id=tc["id"], index=j)],
            )


class FakeLiveKit:
    """Mimics AgentSession: a chat context with the greeting, then one adapter.chat() per caller turn.

    LiveKit gives every spoken reply its own random item_ id and re-sends the whole transcript
    each turn, which is exactly what makes persistence tricky, so the fake does the same.
    """

    def __init__(self, graph, ctx: CallContext, thread_id: str = "room-1"):
        self.adapter = LLMAdapter(
            graph,
            config={"configurable": {"thread_id": thread_id}, "recursion_limit": 25},
            context=ctx,
            stream_mode="custom",
        )
        self.chat_ctx = ChatContext()
        self.chat_ctx.add_message(role="system", content="(LiveKit agent instructions, unused)", id="lk.instructions")
        self.chat_ctx.add_message(role="assistant", content=GREETING, id=shortuuid("item_"))

    async def turn(
        self, user_text: str, barge_in_after_chars: int | None = None, barge_in_after_s: float | None = None
    ) -> str:
        self.chat_ctx.add_message(role="user", content=user_text, id=shortuuid("item_"))
        spoken = ""
        stream = self.adapter.chat(chat_ctx=self.chat_ctx)

        async def consume():
            nonlocal spoken
            async for chunk in stream:
                if chunk.delta and chunk.delta.content:
                    spoken += chunk.delta.content
                if barge_in_after_chars is not None and len(spoken) >= barge_in_after_chars:
                    return  # the caller cut in: LiveKit stops consuming and closes the stream

        try:
            if barge_in_after_s is not None:
                try:
                    await asyncio.wait_for(consume(), barge_in_after_s)
                except asyncio.TimeoutError:
                    pass
            else:
                await consume()
        finally:
            await stream.aclose()  # cancels the graph task, like a real barge-in
        if spoken:
            self.chat_ctx.add_message(role="assistant", content=spoken, id=shortuuid("item_"))
        return spoken


def all_tools() -> list:
    seen = {}
    for tools in TOOLS.values():
        for t in tools:
            seen[t.name] = t
    return list(seen.values())


async def invoke_tool(name: str, args: dict, state: dict | None = None, ctx: CallContext | None = None):
    """Run one tool through a real ToolNode. Returns (tool_message, new_state)."""
    g = StateGraph(CallState, context_schema=CallContext)
    g.add_node("tools", ToolNode(all_tools(), handle_tool_errors=_tool_errors))
    g.add_edge(START, "tools")
    graph = g.compile()
    request = AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": "call_1"}])
    out = await graph.ainvoke({**(state or {}), "messages": [request]}, context=ctx or CallContext())
    return out["messages"][-1], out
