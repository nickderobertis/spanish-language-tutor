import asyncio
import datetime
import logging
from livekit.agents import (
    JobContext,
    AgentSession,
    ConversationItemAddedEvent,
    ChatMessage,
)
import aiofiles
from .constants import TRANSCRIPTS_DIR

logger = logging.getLogger(__name__)


def log_transcriptions_to_file(ctx: JobContext, session: AgentSession):
    log_queue = asyncio.Queue()
    log_file_name = f"transcriptions_{datetime.datetime.now().timestamp()}.log"

    @session.on("conversation_item_added")  # pyright: ignore[reportUntypedFunctionDecorator]
    def on_conversation_item_added(event: ConversationItemAddedEvent):  # pyright: ignore[reportUnusedFunction]
        message = event.item
        if not isinstance(message, ChatMessage):
            return
        label = "ASSISTANT" if message.role == "assistant" else "USER"
        content = "\n".join(part for part in message.content if isinstance(part, str))
        log_queue.put_nowait(f"[{datetime.datetime.now()}] {label}:\n{content}\n\n")

    async def write_transcription():
        async with aiofiles.open(TRANSCRIPTS_DIR / log_file_name, "w") as f:
            while True:
                msg = await log_queue.get()
                if msg is None:
                    break
                await f.write(msg)

    write_task = asyncio.create_task(write_transcription())

    async def finish_queue():
        log_queue.put_nowait(None)
        await write_task
        logger.info(f"Transcriptions logged to {log_file_name}")

    ctx.add_shutdown_callback(finish_queue)
