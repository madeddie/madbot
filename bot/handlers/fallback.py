import logging

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.types import Message

from bot.ai.chat import chat
from bot.utils import md_to_tg

logger = logging.getLogger(__name__)

router = Router()


@router.message(F.text)
async def ai_fallback(message: Message) -> None:
    await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")
    try:
        reply = await chat(message.from_user.id, message.text)
        await message.answer(md_to_tg(reply), parse_mode=ParseMode.MARKDOWN_V2)
    except Exception:
        logger.exception("AI call failed for user %s", message.from_user.id)
        await message.answer("Something went wrong talking to the AI. Try again in a moment.")
