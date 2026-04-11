import logging

from aiogram import F, Router
from aiogram.types import Message

from bot.ai.chat import chat

logger = logging.getLogger(__name__)

router = Router()


@router.message(F.text)
async def ai_fallback(message: Message) -> None:
    await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")
    try:
        reply = await chat(message.from_user.id, message.text)
        await message.answer(reply)
    except Exception:
        logger.exception("AI call failed for user %s", message.from_user.id)
        await message.answer("Something went wrong talking to the AI. Try again in a moment.")
