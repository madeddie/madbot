import asyncio
import importlib
import pkgutil
from collections import defaultdict

import bot.handlers as _handlers_pkg
from ai_sdk import generate_text
from ai_sdk.tool import Tool
from ai_sdk.types import AnyMessage, CoreAssistantMessage, CoreUserMessage

from bot.ai.providers import get_default_model
from bot.config import settings

_model = get_default_model()

# Per-user conversation history keyed by Telegram user_id.
# In-memory only — resets on bot restart.
_history: dict[int, list[AnyMessage]] = defaultdict(list)


def _collect_tools() -> list[Tool]:
    tools: list[Tool] = []
    for mod_info in pkgutil.iter_modules(_handlers_pkg.__path__):
        mod = importlib.import_module(f"bot.handlers.{mod_info.name}")
        if hasattr(mod, "AI_TOOLS"):
            tools.extend(mod.AI_TOOLS)
    return tools


_tools: list[Tool] | None = None


def _get_tools() -> list[Tool]:
    global _tools
    if _tools is None:
        _tools = _collect_tools()
    return _tools


def _trim(user_id: int) -> None:
    max_msgs = settings.max_history_messages
    if len(_history[user_id]) > max_msgs:
        _history[user_id] = _history[user_id][-max_msgs:]


async def chat(user_id: int, user_message: str) -> str:
    """Send a message and return the assistant reply, maintaining per-user history."""
    _history[user_id].append(CoreUserMessage(content=user_message))
    _trim(user_id)

    result = await asyncio.to_thread(
        generate_text,
        model=_model,
        system=settings.system_prompt,
        messages=list(_history[user_id]),
        tools=_get_tools() or None,
    )

    reply = result.text
    _history[user_id].append(CoreAssistantMessage(content=reply))
    _trim(user_id)

    return reply


def clear_history(user_id: int) -> None:
    """Wipe conversation history for a user. Called by /start."""
    _history.pop(user_id, None)
