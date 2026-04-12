"""
Bot self-introspection tools (owner-only).

Exposes four AI tools that let the bot read its own logs, source code, and
runtime state. All tools are withheld from non-owner users by returning an
empty list from the factory.
"""
import pkgutil
from pathlib import Path

from ai_sdk import tool as ai_tool
from pydantic import BaseModel, Field

import bot.handlers as _handlers_pkg
from bot.config import settings

# Project root: madbot/bot/handlers/introspect.py -> parents[2] == madbot/
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ALLOWED_EXTENSIONS = {".py", ".md", ".toml"}


# ---- Pydantic parameter models ----

class _RecentLogsParams(BaseModel):
    n: int = Field(
        default=50, ge=1, le=500,
        description="Number of recent log lines to return.",
    )
    level: str = Field(
        default="",
        description=(
            "Optional log level filter, e.g. 'ERROR', 'WARNING', 'INFO'. "
            "Empty string returns all levels."
        ),
    )


class _ReadSourceFileParams(BaseModel):
    path: str = Field(
        description=(
            "Relative path to the file from the project root, "
            "e.g. 'bot/handlers/echo.py' or 'README.md'."
        ),
    )


# ---- Business logic ----

def _get_recent_logs(n: int = 50, level: str = "") -> str:
    log_file = settings.log_file
    if not log_file:
        return (
            "Log file is not configured. "
            "Set LOG_FILE=/path/to/madbot.log in .env to enable file logging."
        )

    path = Path(log_file)
    if not path.is_file():
        return f"Log file {log_file!r} does not exist yet (bot may not have written to it)."

    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    if level:
        level_tag = f"[{level.upper()}]"
        lines = [line for line in lines if level_tag in line]

    recent = lines[-n:]
    if not recent:
        return "No matching log entries found."

    return "\n".join(recent)


def _list_source_files() -> str:
    files = sorted(
        p.relative_to(_PROJECT_ROOT)
        for p in _PROJECT_ROOT.rglob("*")
        if p.is_file()
        and p.suffix in _ALLOWED_EXTENSIONS
        and ".git" not in p.parts
        and "__pycache__" not in p.parts
        and ".venv" not in p.parts
    )
    if not files:
        return "No source files found."
    return "\n".join(str(f) for f in files)


def _read_source_file(path: str) -> str:
    try:
        target = (_PROJECT_ROOT / path).resolve()
    except Exception:
        return "Invalid path."

    # Security: must stay within project root
    try:
        target.relative_to(_PROJECT_ROOT)
    except ValueError:
        return "Access denied: path must be within the project directory."

    if target.suffix not in _ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(_ALLOWED_EXTENSIONS))
        return f"Access denied: only {allowed} files are readable."

    if not target.is_file():
        return f"File not found: {path}"

    return target.read_text(encoding="utf-8")


def _get_bot_status(user_id: int) -> str:
    from datetime import datetime, timezone

    import bot.main as _main_mod
    from bot.ai.chat import _get_tools_for_user

    now = datetime.now(timezone.utc)
    uptime = now - _main_mod.start_time
    total_seconds = int(uptime.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    handler_count = sum(1 for _ in pkgutil.iter_modules(_handlers_pkg.__path__))
    tool_count = len(_get_tools_for_user(user_id))

    lines = [
        "=== Bot Status ===",
        f"Uptime:          {hours}h {minutes}m {seconds}s",
        f"Provider:        {settings.ai_provider}",
        f"Model:           {settings.ai_model}",
        f"Debug:           {settings.debug}",
        f"Max history:     {settings.max_history_messages} messages",
        f"Loaded handlers: {handler_count}",
        f"AI tools:        {tool_count}",
        f"Log file:        {settings.log_file or '(not configured)'}",
        f"System prompt:   {settings.system_prompt}",
    ]
    return "\n".join(lines)


# ---- Tool factory — called by chat.py with the current user_id ----

def make_introspect_tools(user_id: int) -> list:
    """Return introspection tools, but only for the bot owner."""
    if settings.owner_chat_id == 0 or user_id != settings.owner_chat_id:
        return []

    def _do_get_recent_logs(n: int = 50, level: str = "") -> str:
        return _get_recent_logs(n, level)

    def _do_list_source_files() -> str:
        return _list_source_files()

    def _do_read_source_file(path: str) -> str:
        return _read_source_file(path)

    def _do_get_bot_status() -> str:
        return _get_bot_status(user_id)

    return [
        ai_tool(
            name="get_recent_logs",
            description=(
                "Read the most recent lines from the bot's log file. "
                "Use this to check for errors, warnings, or recent activity. "
                "Optionally filter by log level (ERROR, WARNING, INFO, DEBUG)."
            ),
            parameters=_RecentLogsParams,
            execute=_do_get_recent_logs,
        ),
        ai_tool(
            name="list_source_files",
            description=(
                "List all source files in the bot project (.py, .md, .toml). "
                "Use this to discover what files exist before reading them."
            ),
            parameters={"type": "object", "properties": {}, "required": []},
            execute=_do_list_source_files,
        ),
        ai_tool(
            name="read_source_file",
            description=(
                "Read the contents of a source file in the bot project. "
                "Path must be relative to the project root, "
                "e.g. 'bot/handlers/echo.py' or 'README.md'. "
                "Only .py, .md, and .toml files are accessible."
            ),
            parameters=_ReadSourceFileParams,
            execute=_do_read_source_file,
        ),
        ai_tool(
            name="get_bot_status",
            description=(
                "Get the bot's current runtime status: uptime, AI provider and model, "
                "number of loaded handlers, number of available AI tools, "
                "and configuration summary."
            ),
            parameters={"type": "object", "properties": {}, "required": []},
            execute=_do_get_bot_status,
        ),
    ]
