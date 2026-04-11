from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.ai.chat import clear_history

router = Router()

COMMANDS = {"start": "Reset our conversation"}


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    clear_history(message.from_user.id)
    await message.answer(
        "Hello! I'm madbot.\n"
        "My memory has been wiped clean — we're starting fresh.\n\n"
        "Just talk to me, or use /help to see what I can do."
    )
