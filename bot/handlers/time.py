from datetime import datetime, timezone

from ai_sdk import tool as ai_tool
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router()

COMMANDS = {"time": "Show the current UTC time"}


def _get_time() -> str:
    return datetime.now(timezone.utc).strftime("UTC %Y-%m-%d %H:%M:%S")


AI_TOOLS = [
    ai_tool(
        name="get_time",
        description="Get the current UTC date and time.",
        parameters={"type": "object", "properties": {}, "required": []},
        execute=_get_time,
    )
]


@router.message(Command("time"))
async def cmd_time(message: Message) -> None:
    await message.answer(_get_time())
