import asyncio
import importlib
import logging
import pkgutil
from collections import defaultdict

import bot.handlers as _handlers_pkg
from ai_sdk import generate_text
from ai_sdk.tool import Tool
from ai_sdk.types import AnyMessage, CoreAssistantMessage, CoreUserMessage

from bot import db
from bot.ai.providers import get_default_model
from bot.config import settings

logger = logging.getLogger(__name__)

_model = get_default_model()

# Per-user conversation history keyed by Telegram user_id.
# In-memory only — resets on bot restart.
_history: dict[int, list[AnyMessage]] = defaultdict(list)

# Static tools (from AI_TOOLS lists) collected once and cached.
_static_tools: list[Tool] | None = None
# Factory callables (make_schedule_tools) — one per handler module that exports one.
_tool_factories: list | None = None


def _collect_tools_once() -> tuple[list[Tool], list]:
    """Scan handler modules and collect static tools and per-user tool factories.

    A per-user tool factory is any module-level callable named make_*_tools.
    """
    static: list[Tool] = []
    factories = []
    for mod_info in pkgutil.iter_modules(_handlers_pkg.__path__):
        mod = importlib.import_module(f"bot.handlers.{mod_info.name}")
        if hasattr(mod, "AI_TOOLS"):
            static.extend(mod.AI_TOOLS)
        for attr in dir(mod):
            if attr.startswith("make_") and attr.endswith("_tools") and callable(getattr(mod, attr)):
                factories.append(getattr(mod, attr))
    return static, factories


def _get_tools_for_user(user_id: int) -> list[Tool]:
    """Return the full tool list for a given user (static tools + user-bound dynamic tools)."""
    global _static_tools, _tool_factories
    if _static_tools is None or _tool_factories is None:
        _static_tools, _tool_factories = _collect_tools_once()
    tools = list(_static_tools)
    for factory in _tool_factories:
        tools.extend(factory(user_id))
    return tools


def _build_system(user_id: int, extra: str = "") -> str:
    """Return the system prompt, appending stored facts and any extra suffix."""
    parts = [settings.system_prompt]
    facts = db.get_facts(user_id)
    if facts:
        lines = "\n".join(f"- {k}: {v}" for k, v in facts.items())
        parts.append(f"Known facts about the user:\n{lines}")
    if extra:
        parts.append(extra)
    return "\n\n".join(parts)


def _trim(user_id: int) -> None:
    max_msgs = settings.max_history_messages
    if len(_history[user_id]) > max_msgs:
        _history[user_id] = _history[user_id][-max_msgs:]


async def chat(user_id: int, user_message: str) -> str:
    """Send a message and return the assistant reply, maintaining per-user history."""
    logger.debug("chat: user=%d message=%r history_len=%d", user_id, user_message, len(_history[user_id]))
    _history[user_id].append(CoreUserMessage(content=user_message))
    _trim(user_id)

    result = await asyncio.to_thread(
        generate_text,
        model=_model,
        system=_build_system(user_id),
        messages=list(_history[user_id]),
        tools=_get_tools_for_user(user_id) or None,
    )

    logger.debug("chat: user=%d tool_calls=%r reply=%r", user_id, getattr(result, "tool_calls", None), result.text)
    reply = result.text
    _history[user_id].append(CoreAssistantMessage(content=reply))
    _trim(user_id)

    return reply


async def run_scheduled_query(user_id: int, query: str) -> None:
    """Execute an AI query for a scheduled job.

    Runs an isolated single-turn conversation (does not touch _history).
    Sends the result to the user via the bot.
    """
    from bot.scheduler import get_bot  # late import — avoids circular at module level

    logger.debug("run_scheduled_query: user=%d query=%r", user_id, query)

    system = _build_system(
        user_id,
        extra=(
            "This is a scheduled message triggered automatically. "
            "Respond naturally as if you initiated the conversation."
        ),
    )

    result = await asyncio.to_thread(
        generate_text,
        model=_model,
        system=system,
        messages=[CoreUserMessage(content=query)],
        tools=_get_tools_for_user(user_id) or None,
    )

    logger.debug("run_scheduled_query: user=%d tool_calls=%r reply=%r", user_id, getattr(result, "tool_calls", None), result.text)

    from aiogram.enums import ParseMode

    from bot.utils import md_to_tg

    bot = get_bot()
    try:
        await bot.send_message(user_id, md_to_tg(result.text), parse_mode=ParseMode.MARKDOWN_V2)
    except Exception:
        logger.exception("Failed to send scheduled message to user %d", user_id)


def clear_history(user_id: int) -> None:
    """Wipe conversation history for a user. Called by /start."""
    _history.pop(user_id, None)
