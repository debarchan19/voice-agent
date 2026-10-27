from dotenv import load_dotenv
from livekit import agents
from livekit.agents import AgentServer, AgentSession, JobContext, JobProcess
from livekit.plugins import anthropic, cartesia, deepgram, silero
from livekit.plugins.turn_detector.english import EnglishModel

from support import GreeterAgent, UserData

load_dotenv()


def prewarm(proc: JobProcess) -> None:
    # Load VAD once per worker process, not once per call.
    proc.userdata["vad"] = silero.VAD.load()


server = AgentServer(setup_fnc=prewarm)


@server.rtc_session()
async def entrypoint(ctx: JobContext) -> None:
    session = AgentSession[UserData](
        userdata=UserData(room=ctx.room),
        stt=deepgram.STT(model="nova-3", interim_results=True),
        llm=anthropic.LLM(model="claude-sonnet-4-6"),
        tts=cartesia.TTS(model="sonic-2"),
        vad=ctx.proc.userdata["vad"],
        turn_handling={
            "turn_detection": EnglishModel(),
            "interruption": {"enabled": True},
        },
    )

    await session.start(room=ctx.room, agent=GreeterAgent())
    await ctx.connect()


if __name__ == "__main__":
    agents.cli.run_app(server)
