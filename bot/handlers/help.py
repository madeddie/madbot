import importlib
import pkgutil

import bot.handlers as _handlers_pkg
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router()

COMMANDS = {"help": "Show this message"}


def _collect_commands() -> dict[str, str]:
    commands: dict[str, str] = {}
    for mod_info in pkgutil.iter_modules(_handlers_pkg.__path__):
        mod = importlib.import_module(f"bot.handlers.{mod_info.name}")
        if hasattr(mod, "COMMANDS"):
            commands.update(mod.COMMANDS)
    return commands


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    commands = _collect_commands()
    lines = [f"/{cmd} — {desc}" for cmd, desc in sorted(commands.items())]
    await message.answer("<b>Commands</b>\n" + "\n".join(lines))
