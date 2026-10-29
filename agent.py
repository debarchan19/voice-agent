"""The LiveKit voice layer: speech in, speech out, turn-taking and interruptions.

Everything the agent *thinks* (who it is talking to, which tools to call, when to hand off) lives
in the LangGraph graph in `wismo/`. This file only wires the voice pipeline around it:

    caller -> Deepgram STT -> LLMAdapter -> LangGraph graph -> Cartesia TTS -> caller
"""

from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langgraph.checkpoint.memory import InMemorySaver
from livekit import agents
from livekit.agents import Agent, AgentServer, AgentSession, JobContext, JobProcess
from livekit.plugins import cartesia, deepgram, langchain, silero
from livekit.plugins.turn_detector.english import EnglishModel

from wismo import GREETING, CallContext, build_graph, report

load_dotenv()


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
    graph = build_graph(ChatAnthropic(model="claude-sonnet-4-6", max_tokens=400), checkpointer=InMemorySaver())

    session = AgentSession(
        stt=deepgram.STT(model="nova-3", interim_results=True),
        # "custom" stream mode: only text the graph deliberately streams is spoken, so tool
        # results and internal notes can never be read aloud.
        llm=langchain.LLMAdapter(
            graph,
            config={
                "configurable": {"thread_id": f"{ctx.room.name}:{ctx.job.id}"},
                "recursion_limit": 25,
            },
            context=call,
            stream_mode="custom",
        ),
        tts=cartesia.TTS(model="sonic-2"),
        vad=ctx.proc.userdata["vad"],
        turn_handling={
            "turn_detection": EnglishModel(),
            "interruption": {"enabled": True},
            # LiveKit starts a reply speculatively before the caller finishes. Here that would
            # run tools early (burning a verification attempt, or worse), so it stays off.
            "preemptive_generation": {"enabled": False},
        },
    )

    await session.start(room=ctx.room, agent=VoiceShell(call))
    await ctx.connect()


if __name__ == "__main__":
    agents.cli.run_app(server)
