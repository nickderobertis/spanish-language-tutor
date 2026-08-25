import asyncio
import datetime
import logging
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Protocol

import aiofiles
from livekit.agents import (
    AgentSession,
    ChatMessage,
    ConversationItemAddedEvent,
)

from .constants import TRANSCRIPTS_DIR

logger = logging.getLogger(__name__)


class ShutdownCallbackRegistry(Protocol):
    """The only part of the LiveKit job context transcript logging needs."""

    def add_shutdown_callback(
        self, callback: Callable[[], Coroutine[None, None, None]]
    ) -> None: ...


def log_transcriptions_to_file(
    ctx: ShutdownCallbackRegistry,
    session: AgentSession,
    transcripts_dir: Path = TRANSCRIPTS_DIR,
) -> Path:
    log_queue: asyncio.Queue[str | None] = asyncio.Queue()
    now = datetime.datetime.now(tz=datetime.UTC)
    log_file_name = f"transcriptions_{now.timestamp()}.log"
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    log_file_path = transcripts_dir / log_file_name

    @session.on("conversation_item_added")  # pyright: ignore[reportUntypedFunctionDecorator]
    def on_conversation_item_added(event: ConversationItemAddedEvent):  # pyright: ignore[reportUnusedFunction]
        message = event.item
        if not isinstance(message, ChatMessage):
            return
        label = "ASSISTANT" if message.role == "assistant" else "USER"
        content = "\n".join(part for part in message.content if isinstance(part, str))
        timestamp = datetime.datetime.now(tz=datetime.UTC)
        log_queue.put_nowait(f"[{timestamp}] {label}:\n{content}\n\n")

    async def write_transcription():
        async with aiofiles.open(log_file_path, "w") as f:
            while True:
                msg = await log_queue.get()
                if msg is None:
                    break
                await f.write(msg)

    write_task = asyncio.create_task(write_transcription())

    async def finish_queue() -> None:
        log_queue.put_nowait(None)
        await write_task
        logger.info(f"Transcriptions logged to {log_file_name}")

    ctx.add_shutdown_callback(finish_queue)

    return log_file_path
