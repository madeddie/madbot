import asyncio
import logging
import os
import sys

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.config import settings

router = Router()
logger = logging.getLogger(__name__)

COMMANDS = {
    "quit": "Shut down the bot",
    "restart": "Restart the bot",
    "gitpull": "Pull latest code from git",
}


def _is_owner(message: Message) -> bool:
    return settings.owner_chat_id != 0 and message.from_user.id == settings.owner_chat_id


@router.message(Command("quit"))
async def cmd_quit(message: Message) -> None:
    if not _is_owner(message):
        await message.answer("Not authorised.")
        return
    await message.answer("Shutting down.")
    logger.info("Quit requested by owner.")
    os._exit(0)


@router.message(Command("restart"))
async def cmd_restart(message: Message) -> None:
    if not _is_owner(message):
        await message.answer("Not authorised.")
        return
    await message.answer("Restarting...")
    logger.info("Restart requested by owner.")
    os.execv(sys.executable, [sys.executable] + sys.argv)


@router.message(Command("gitpull"))
async def cmd_gitpull(message: Message) -> None:
    if not _is_owner(message):
        await message.answer("Not authorised.")
        return
    proc = await asyncio.create_subprocess_exec(
        "git", "pull",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await proc.communicate()
    output = stdout.decode().strip()
    await message.answer(f"<pre>{output}</pre>")
