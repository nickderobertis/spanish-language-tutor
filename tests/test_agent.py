"""Tests for the migrated LiveKit Agents 1.x tutor surfaces.

Every test here constructs the real migrated objects from the installed
livekit-agents / livekit-plugins-openai releases. Nothing contacts a LiveKit
server or a paid provider: the realtime model is only ever constructed, never
connected, and the placeholder API key below is not a credential.
"""

from collections.abc import Awaitable, Callable, Coroutine
from pathlib import Path

import pytest
from livekit.agents import (
    Agent,
    AgentHandoff,
    AgentServer,
    AgentSession,
    ChatMessage,
    ConversationItemAddedEvent,
)
from livekit.agents.llm import is_function_tool
from livekit.agents.llm.tool_context import FunctionTool, get_function_info
from livekit.plugins import openai as livekit_openai
from livekit.plugins import silero
from livekit.plugins.openai.realtime.realtime_model import (
    RealtimeModel,
    process_base_url,
)

from language_tutor import agent as tutor_agent
from language_tutor.constants import (
    GREETING_INSTRUCTIONS,
    GREETING_PROMPT,
    REALTIME_MODEL,
    SUMMARY_MODEL,
    SYSTEM_PROMPT,
    TRANSCRIPTION_LANGUAGE,
    TRANSCRIPTION_MODEL,
)
from language_tutor.topics.constants import TOPICS
from language_tutor.transcription import log_transcriptions_to_file
from language_tutor.web_search import build_summarization_llm

PLACEHOLDER_API_KEY = "placeholder-not-a-credential"


@pytest.fixture(autouse=True)
def placeholder_openai_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """OpenAI clients refuse to construct without a key; no request is made."""
    monkeypatch.setenv("OPENAI_API_KEY", PLACEHOLDER_API_KEY)


def tools_by_name(agent: Agent) -> dict[str, FunctionTool]:
    return {
        get_function_info(tool).name: tool
        for tool in agent.tools
        if is_function_tool(tool)
    }


class RecordingJobContext:
    """Stands in for the LiveKit job runtime's shutdown-callback registry."""

    def __init__(self) -> None:
        super().__init__()
        self.shutdown_callbacks: list[Callable[[], Coroutine[None, None, None]]] = []

    def add_shutdown_callback(
        self, callback: Callable[[], Coroutine[None, None, None]]
    ) -> None:
        self.shutdown_callbacks.append(callback)


def test_realtime_plugin_accepts_and_forwards_the_explicit_model_id() -> None:
    """Contract test against the installed plugin: the exact ID is forwarded."""
    model = livekit_openai.realtime.RealtimeModel(model="gpt-realtime-2.1")

    assert model.model == "gpt-realtime-2.1"
    assert (
        process_base_url("https://api.openai.com/v1", model.model)
        == "wss://api.openai.com/v1/realtime?model=gpt-realtime-2.1"
    )


def test_realtime_model_id_is_not_the_plugin_default() -> None:
    """The pin is explicit, so it must differ from whatever the plugin defaults to."""
    assert REALTIME_MODEL == "gpt-realtime-2.1"
    assert livekit_openai.realtime.RealtimeModel().model != REALTIME_MODEL


@pytest.mark.anyio
async def test_session_pins_the_realtime_model_and_spanish_transcription() -> None:
    session = tutor_agent.build_session()

    assert isinstance(session.llm, RealtimeModel)
    assert session.llm.model == REALTIME_MODEL

    transcription = session.llm._opts.input_audio_transcription  # pyright: ignore[reportPrivateUsage]
    assert transcription is not None
    assert transcription.model == TRANSCRIPTION_MODEL
    assert transcription.language == TRANSCRIPTION_LANGUAGE


@pytest.mark.anyio
async def test_session_keeps_the_long_silence_vad_window() -> None:
    session = tutor_agent.build_session()

    assert isinstance(session.vad, silero.VAD)
    assert session.vad.min_silence_duration == tutor_agent.MIN_SILENCE_DURATION


def test_room_input_options_keep_background_voice_cancellation() -> None:
    options = tutor_agent.build_room_input_options()

    assert options.noise_cancellation is not None


def test_assistant_keeps_the_mexico_city_persona_and_correction_style() -> None:
    instructions = tutor_agent.Assistant().instructions

    assert isinstance(instructions, str)
    assert instructions == SYSTEM_PROMPT
    assert "Mexico City" in instructions
    assert "brief correction" in instructions


def test_greeting_instructions_combine_the_persona_and_the_greeting() -> None:
    assert GREETING_INSTRUCTIONS.startswith(SYSTEM_PROMPT)
    assert GREETING_INSTRUCTIONS.endswith(GREETING_PROMPT)


def test_assistant_exposes_both_function_tools_with_their_descriptions() -> None:
    tools = tools_by_name(tutor_agent.Assistant())

    assert set(tools) == {"web_search", "random_topic"}
    assert (
        get_function_info(tools["web_search"]).description
        == "Perform a web search and return the summary of the results."
    )
    assert (
        get_function_info(tools["random_topic"]).description
        == "Return a random topic for conversation."
    )


@pytest.mark.anyio
async def test_random_topic_tool_returns_a_known_conversation_topic() -> None:
    tool = tools_by_name(tutor_agent.Assistant())["random_topic"]

    topic = await tool()

    assert topic in TOPICS


@pytest.mark.anyio
async def test_web_search_tool_delegates_to_the_search_summariser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, int]] = []

    async def fake_summary(query: str, max_results: int = 5) -> str:
        calls.append((query, max_results))
        return "resumen en español"

    monkeypatch.setattr(tutor_agent, "web_search_to_summary", fake_summary)
    tool = tools_by_name(tutor_agent.Assistant())["web_search"]

    result = await tool(query="clima en la Ciudad de México")

    assert result == "resumen en español"
    assert calls == [("clima en la Ciudad de México", 10)]


def test_summarization_llm_is_pinned_to_the_low_cost_model() -> None:
    llm = build_summarization_llm()

    assert getattr(llm, "model_name", None) == SUMMARY_MODEL
    assert getattr(llm, "temperature", None) == 0


def test_agent_server_registers_the_rtc_session_entrypoint() -> None:
    assert isinstance(tutor_agent.server, AgentServer)
    assert tutor_agent.server._entrypoint_fnc is tutor_agent.entrypoint  # pyright: ignore[reportPrivateUsage]


def test_module_cli_discovers_the_agent_server_from_the_launch_path() -> None:
    """`python -m livekit.agents start <path>` resolves the server this way."""
    from livekit.agents.__main__ import (
        _discover_server,  # pyright: ignore[reportPrivateUsage]
    )

    discovered = _discover_server("language_tutor/agent.py")

    assert discovered is tutor_agent.server


@pytest.mark.anyio
async def test_transcripts_are_written_in_spanish_and_flushed_on_shutdown(
    tmp_path: Path,
) -> None:
    session = AgentSession()
    ctx = RecordingJobContext()

    log_file = log_transcriptions_to_file(ctx, session, transcripts_dir=tmp_path)

    session.emit(
        "conversation_item_added",
        ConversationItemAddedEvent(
            item=ChatMessage(role="user", content=["Buenos días, maestro"])
        ),
    )
    session.emit(
        "conversation_item_added",
        ConversationItemAddedEvent(
            item=ChatMessage(
                role="assistant", content=["¡Buenos días! ¿Cómo amaneció?"]
            )
        ),
    )

    assert ctx.shutdown_callbacks, "shutdown flush was never registered"
    for callback in ctx.shutdown_callbacks:
        await callback()

    written = log_file.read_text(encoding="utf-8")
    assert "USER:\nBuenos días, maestro" in written
    assert "ASSISTANT:\n¡Buenos días! ¿Cómo amaneció?" in written


@pytest.mark.anyio
async def test_transcript_logging_ignores_non_message_conversation_items(
    tmp_path: Path,
) -> None:
    session = AgentSession()
    ctx = RecordingJobContext()

    log_file = log_transcriptions_to_file(ctx, session, transcripts_dir=tmp_path)

    session.emit(
        "conversation_item_added",
        ConversationItemAddedEvent(
            item=AgentHandoff(old_agent_id="tutor", new_agent_id="tutor")
        ),
    )

    flush: Awaitable[None] = ctx.shutdown_callbacks[0]()
    await flush

    assert log_file.read_text(encoding="utf-8") == ""
