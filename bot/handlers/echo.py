from ai_sdk import tool as ai_tool
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from pydantic import BaseModel, Field

router = Router()

COMMANDS = {"echo": "Repeat the given text"}


class _EchoParams(BaseModel):
    text: str = Field(description="The text to echo back.")


def _echo(text: str) -> str:
    return text


AI_TOOLS = [
    ai_tool(
        name="echo",
        description="Repeat the given text back verbatim.",
        parameters=_EchoParams,
        execute=_echo,
    )
]


@router.message(Command("echo"))
async def cmd_echo(message: Message) -> None:
    text = message.text.removeprefix("/echo").strip()
    if text:
        await message.answer(_echo(text))
    else:
        await message.answer("Usage: /echo &lt;text&gt;")
