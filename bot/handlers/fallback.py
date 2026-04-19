import io
import logging

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.types import Message

from bot.ai.chat import chat
from bot.utils import md_to_tg, typing_indicator

logger = logging.getLogger(__name__)

router = Router()


@router.message(F.text)
async def ai_fallback(message: Message) -> None:
    try:
        async with typing_indicator(message.bot, message.chat.id):
            reply = await chat(message.from_user.id, message.text)
        await message.answer(md_to_tg(reply), parse_mode=ParseMode.MARKDOWN_V2)
    except Exception:
        logger.exception("AI call failed for user %s", message.from_user.id)
        await message.answer("Something went wrong talking to the AI. Try again in a moment.")


@router.message(F.photo)
async def ai_photo(message: Message) -> None:
    photo = message.photo[-1]  # highest resolution
    text = (message.caption or "").strip() or "What is in this image?"
    try:
        file_info = await message.bot.get_file(photo.file_id)
        buf = io.BytesIO()
        await message.bot.download_file(file_info.file_path, destination=buf)
        async with typing_indicator(message.bot, message.chat.id):
            reply = await chat(message.from_user.id, text, image_bytes=buf.getvalue())
        await message.answer(md_to_tg(reply), parse_mode=ParseMode.MARKDOWN_V2)
    except Exception:
        logger.exception("AI photo call failed for user %s", message.from_user.id)
        await message.answer("Something went wrong analysing the image. Try again in a moment.")
