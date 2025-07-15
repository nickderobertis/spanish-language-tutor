from livekit import agents
from livekit.agents.voice import AgentSession, Agent, room_io
from livekit.plugins import openai, silero, noise_cancellation
from openai.types.beta.realtime.session import InputAudioTranscription

from language_tutor.transcription import log_transcriptions_to_file
from .constants import SYSTEM_PROMPT, GREETING_PROMPT


class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(instructions=SYSTEM_PROMPT)


async def entrypoint(ctx: agents.JobContext):
    await ctx.connect()

    session = AgentSession(
        llm=openai.realtime.RealtimeModel(
            input_audio_transcription=InputAudioTranscription(
                model="gpt-4o-transcribe",
                language="es",
            )
        ),
        vad=silero.VAD.load(min_silence_duration=3),
    )

    log_transcriptions_to_file(ctx, session)

    await session.start(
        room=ctx.room,
        agent=Assistant(),
        room_input_options=room_io.RoomInputOptions(
            noise_cancellation=noise_cancellation.BVC()
        ),
    )

    await session.generate_reply(
        instructions=SYSTEM_PROMPT + "\n\n" + GREETING_PROMPT,
    )


if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint))
