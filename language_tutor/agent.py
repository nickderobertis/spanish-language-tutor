from livekit import agents
from livekit.agents.voice import AgentSession, Agent
from livekit.plugins import openai, silero

from language_tutor.transcription import log_transcriptions_to_file
from .constants import SYSTEM_PROMPT, GREETING_PROMPT


class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(instructions=SYSTEM_PROMPT)


async def entrypoint(ctx: agents.JobContext):
    await ctx.connect()

    session = AgentSession(llm=openai.realtime.RealtimeModel(), vad=silero.VAD.load())

    log_transcriptions_to_file(ctx, session)

    await session.start(room=ctx.room, agent=Assistant())

    await session.generate_reply(
        instructions=SYSTEM_PROMPT + "\n\n" + GREETING_PROMPT,
    )


if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint))
