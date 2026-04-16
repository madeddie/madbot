import asyncio
from contextlib import asynccontextmanager

import telegramify_markdown


def md_to_tg(text: str) -> str:
    """Convert Markdown to Telegram MarkdownV2."""
    return telegramify_markdown.markdownify(text)


@asynccontextmanager
async def typing_indicator(bot, chat_id: int, interval: float = 4.0):
    """Continuously send the 'typing' chat action until the context exits."""
    async def _loop():
        while True:
            try:
                await bot.send_chat_action(chat_id=chat_id, action="typing")
            except Exception:
                pass  # never let a failed send_chat_action kill the body
            await asyncio.sleep(interval)

    task = asyncio.create_task(_loop())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
