from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    RoomInputOptions,
    function_tool,
)
from livekit.plugins import noise_cancellation, openai, silero
from openai.types.realtime import AudioTranscription

from language_tutor.transcription import log_transcriptions_to_file

from .constants import (
    GREETING_INSTRUCTIONS,
    REALTIME_MODEL,
    SYSTEM_PROMPT,
    TRANSCRIPTION_LANGUAGE,
    TRANSCRIPTION_MODEL,
)
from .topics import get_random_topic
from .web_search import web_search_to_summary

MIN_SILENCE_DURATION = 3


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


def build_session() -> AgentSession:
    """Build the realtime session the tutor speaks through."""
    return AgentSession(
        llm=openai.realtime.RealtimeModel(
            model=REALTIME_MODEL,
            input_audio_transcription=AudioTranscription(
                model=TRANSCRIPTION_MODEL,
                language=TRANSCRIPTION_LANGUAGE,
            ),
        ),
        vad=silero.VAD.load(min_silence_duration=MIN_SILENCE_DURATION),
    )


def build_room_input_options() -> RoomInputOptions:
    """Room input wiring, including background-voice cancellation."""
    return RoomInputOptions(noise_cancellation=noise_cancellation.BVC())


server = AgentServer()


@server.rtc_session()
async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()

    session = build_session()

    log_transcriptions_to_file(ctx, session)

    await session.start(
        Assistant(),
        room=ctx.room,
        room_input_options=build_room_input_options(),
    )

    await session.generate_reply(instructions=GREETING_INSTRUCTIONS)
