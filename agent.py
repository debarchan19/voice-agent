"""The LiveKit voice layer: speech in, speech out, turn-taking and interruptions.

Everything the agent *thinks* (who it is talking to, which tools to call, when to hand off) lives
in the LangGraph graph in `wismo/`. This file only wires the voice pipeline around it:

    caller -> Deepgram STT -> LLMAdapter -> LangGraph graph -> Cartesia TTS -> caller

It also feeds the browser's demo views: a live trace of each graph run (`CallTracer`), the latency
and barge-ins of every spoken reply, and an after-call summary when the caller presses End call.
"""

import asyncio
import json
import os

from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langgraph.checkpoint.memory import InMemorySaver
from livekit import agents, rtc
from livekit.agents import Agent, AgentServer, AgentSession, ConversationItemAddedEvent, JobContext, JobProcess
from livekit.agents.llm import ChatMessage
from livekit.plugins import cartesia, deepgram, langchain, silero
from livekit.plugins.turn_detector.english import EnglishModel

from wismo import GREETING, CallContext, CallTracer, build_graph, report, summarize_call
from wismo.panel import TRACE_TOPIC, send, voice_turn
from wismo.trace import now_ms

load_dotenv()

MODEL = "claude-sonnet-4-6"


class VoiceShell(Agent):
    """A LiveKit Agent with no brain of its own: the graph supplies every prompt and tool."""

    def __init__(self, call: CallContext) -> None:
        super().__init__(instructions="Voice shell. The LangGraph graph supplies all prompts.")
        self.call = call

    async def on_enter(self) -> None:
        await report(self.call, {"active_agent": "greeter"}, "Call started")
        # Fixed wording, so the first line of every call is predictable.
        await self.session.say(GREETING)


def prewarm(proc: JobProcess) -> None:
    # Load VAD once per worker process, not once per call.
    proc.userdata["vad"] = silero.VAD.load()


server = AgentServer(setup_fnc=prewarm)


@server.rtc_session()
async def entrypoint(ctx: JobContext) -> None:
    call = CallContext(room=ctx.room)
    # One graph (and one in-memory checkpoint) per call, so nothing leaks between callers.
    graph = build_graph(ChatAnthropic(model=MODEL, max_tokens=400), checkpointer=InMemorySaver())
    thread_id = f"{ctx.room.name}:{ctx.job.id}"
    config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": 25,
        # The browser's live graph and waterfall. With LANGSMITH_TRACING=true the same runs also
        # go to LangSmith, named and grouped into one thread per call.
        "callbacks": [CallTracer(call)],
        "run_name": "Delivery Desk turn",
        "tags": ["delivery-desk"],
        "metadata": {"thread_id": thread_id},
    }

    session = AgentSession(
        stt=deepgram.STT(model="nova-3", interim_results=True),
        # "custom" stream mode: only text the graph deliberately streams is spoken, so tool
        # results and internal notes can never be read aloud.
        llm=langchain.LLMAdapter(graph, config=config, context=call, stream_mode="custom"),
        # sonic-3: Cartesia's most natural-sounding model, and slightly quicker to first audio.
        # CARTESIA_VOICE_ID in .env picks the voice; unset, Cartesia's default voice is used.
        tts=cartesia.TTS(model="sonic-3", **({"voice": voice} if (voice := os.getenv("CARTESIA_VOICE_ID")) else {})),
        vad=ctx.proc.userdata["vad"],
        turn_handling={
            "turn_detection": EnglishModel(),
            # Once the turn detector judges the sentence finished, reply after 0.3s instead of the
            # default 0.5s. Mid-sentence pauses are still covered by the detector (up to max_delay).
            "endpointing": {"min_delay": 0.3, "max_delay": 3.0},
            "interruption": {"enabled": True},
            # LiveKit starts a reply speculatively before the caller finishes. Here that would
            # run tools early (burning a verification attempt, or worse), so it stays off.
            "preemptive_generation": {"enabled": False},
        },
    )

    # Latency of every spoken turn, and whether the caller cut the agent off.
    pending: set[asyncio.Task] = set()

    @session.on("conversation_item_added")
    def on_item(ev: ConversationItemAddedEvent) -> None:
        item = ev.item
        if not isinstance(item, ChatMessage) or item.role not in ("user", "assistant"):
            return
        data = voice_turn(item.role, dict(item.metrics or {}), item.interrupted, now_ms())
        task = asyncio.create_task(send(call, data, TRACE_TOPIC))
        pending.add(task)
        task.add_done_callback(pending.discard)

    async def wrap_up(_: rtc.RpcInvocationData) -> str:
        """Called by the browser's End call button, just before it hangs up."""
        state = (await graph.aget_state({"configurable": {"thread_id": thread_id}})).values
        transcript = [
            (m.role, m.text_content or "") for m in session.history.messages() if m.role in ("user", "assistant")
        ]
        return json.dumps(await summarize_call(ChatAnthropic(model=MODEL, max_tokens=1000), transcript, state, call))

    await session.start(room=ctx.room, agent=VoiceShell(call))
    await ctx.connect()
    ctx.room.local_participant.register_rpc_method("wrap_up", wrap_up)


if __name__ == "__main__":
    agents.cli.run_app(server)
