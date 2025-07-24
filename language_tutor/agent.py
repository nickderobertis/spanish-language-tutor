from livekit import agents
from livekit.agents.voice import AgentSession, Agent, room_io
from livekit.agents.llm import function_tool
from livekit.plugins import openai, silero, noise_cancellation
from openai.types.beta.realtime.session import InputAudioTranscription


from language_tutor.transcription import log_transcriptions_to_file
from .web_search import web_search_to_summary
from .topics import get_random_topic
from .constants import SYSTEM_PROMPT, GREETING_PROMPT


class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(instructions=SYSTEM_PROMPT)

    @function_tool
    async def web_search(self, query: str) -> str:
        """
        Perform a web search and return the summary of the results.
        """
        print(f"Performing web search for: {query}")
        summary = await web_search_to_summary(query, max_results=10)
        print(f"Web search summary: {summary}")
        return summary

    @function_tool
    async def random_topic(self) -> str:
        """
        Return a random topic for conversation.
        """
        return get_random_topic()


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
