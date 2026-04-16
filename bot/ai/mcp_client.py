"""MCP (Model Context Protocol) client integration for madbot.

Manages persistent connections to external MCP servers in a dedicated
background event loop thread. Tool execute functions bridge from the
generate_text thread pool to the background loop via
asyncio.run_coroutine_threadsafe().

Supports Claude Desktop-style JSON config (mcp_servers.json):
    {
      "mcpServers": {
        "my-server": {
          "command": "npx",
          "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
        },
        "my-http-server": {
          "url": "http://localhost:8000/mcp"
        }
      }
    }

Graceful degradation: if mcp_servers.json does not exist, or a server
fails to connect, get_mcp_tools() returns only successfully loaded tools.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from ai_sdk import tool as ai_tool
from ai_sdk.tool import Tool

logger = logging.getLogger(__name__)

# Background event loop that owns all MCP I/O.
# Tool execute functions submit coroutines here via run_coroutine_threadsafe.
_bg_loop: asyncio.AbstractEventLoop | None = None
_bg_thread: threading.Thread | None = None

# AsyncExitStack keeping all MCP sessions alive for the bot's lifetime.
_exit_stack: AsyncExitStack | None = None

# Cached tool list populated by init().
_mcp_tools: list[Tool] = []


def _ensure_bg_loop() -> asyncio.AbstractEventLoop:
    """Start the background event loop thread if not already running."""
    global _bg_loop, _bg_thread
    if _bg_loop is not None:
        return _bg_loop
    _bg_loop = asyncio.new_event_loop()
    _bg_thread = threading.Thread(
        target=_bg_loop.run_forever, daemon=True, name="mcp-bg"
    )
    _bg_thread.start()
    return _bg_loop


def _run_in_bg(coro: Any, timeout: float = 30) -> Any:
    """Submit *coro* to the background loop and block until done."""
    future = asyncio.run_coroutine_threadsafe(coro, _bg_loop)
    return future.result(timeout=timeout)


async def _connect_server(
    name: str, config: dict, exit_stack: AsyncExitStack
) -> list[Tool]:
    """Connect to one MCP server and return its tools as ai_sdk Tool objects."""
    from mcp import ClientSession

    safe_name = name.replace("-", "_").replace(" ", "_")

    if "url" in config:
        from mcp.client.streamable_http import streamable_http_client

        cm = streamable_http_client(config["url"])
    elif "command" in config:
        from mcp.client.stdio import StdioServerParameters, stdio_client

        params = StdioServerParameters(
            command=config["command"],
            args=config.get("args", []),
            env=config.get("env"),
        )
        cm = stdio_client(params)
    else:
        logger.warning("MCP server %r: no 'url' or 'command' — skipping", name)
        return []

    streams = await exit_stack.enter_async_context(cm)
    read, write = streams[0], streams[1]  # stdio → 2-tuple; http → 3-tuple

    session: ClientSession = await exit_stack.enter_async_context(
        ClientSession(read, write)
    )
    await session.initialize()

    result = await session.list_tools()

    tools: list[Tool] = []
    for t in result.tools:
        tool_name = t.name
        prefixed_name = f"{safe_name}__{tool_name}"

        def _make_execute(sess: ClientSession, raw_name: str):
            def execute(**kwargs: Any) -> str:
                async def _call() -> str:
                    r = await sess.call_tool(raw_name, kwargs)
                    if r.isError:
                        parts = [c.text for c in r.content if hasattr(c, "text")]
                        return f"[MCP error] {' '.join(parts)}"
                    parts = [c.text for c in r.content if hasattr(c, "text")]
                    return "\n".join(parts) if parts else "(no output)"

                return _run_in_bg(_call())

            return execute

        tools.append(
            ai_tool(
                name=prefixed_name,
                description=f"[{name}] {t.description or ''}",
                parameters=t.inputSchema,
                execute=_make_execute(session, tool_name),
            )
        )

    logger.info("MCP server %r: %d tool(s) loaded", name, len(tools))
    return tools


async def _async_init(config_path: Path) -> list[Tool]:
    """Connect to all configured MCP servers. Runs inside the background loop."""
    global _exit_stack

    if not config_path.exists():
        logger.debug("No MCP config at %s — skipping MCP", config_path)
        return []

    try:
        raw = json.loads(config_path.read_text())
    except Exception:
        logger.exception("Failed to parse %s — skipping MCP", config_path)
        return []

    servers: dict = raw.get("mcpServers", {})
    if not servers:
        logger.debug("No mcpServers entries in %s", config_path)
        return []

    _exit_stack = AsyncExitStack()
    await _exit_stack.__aenter__()

    all_tools: list[Tool] = []
    for name, server_config in servers.items():
        try:
            all_tools.extend(await _connect_server(name, server_config, _exit_stack))
        except Exception:
            logger.exception("MCP server %r: connection failed — skipping", name)

    return all_tools


async def init(config_path: Path) -> None:
    """Connect to all configured MCP servers.

    Must be awaited once at startup (before the bot starts polling).
    Uses asyncio.wrap_future so the main event loop is not blocked during
    connection establishment.
    """
    global _mcp_tools

    _ensure_bg_loop()

    # Submit the async init to the background loop, then await the future
    # on the main loop without blocking it.
    future = asyncio.run_coroutine_threadsafe(_async_init(config_path), _bg_loop)
    _mcp_tools = await asyncio.wrap_future(future)

    logger.info("MCP ready: %d tool(s) available", len(_mcp_tools))


async def shutdown() -> None:
    """Close all MCP sessions. Call from the bot's shutdown path."""
    global _exit_stack, _bg_loop
    if _exit_stack is not None and _bg_loop is not None:
        try:
            future = asyncio.run_coroutine_threadsafe(
                _exit_stack.__aexit__(None, None, None), _bg_loop
            )
            await asyncio.wrap_future(future)
        except Exception:
            logger.exception("Error closing MCP sessions")
    if _bg_loop is not None:
        _bg_loop.call_soon_threadsafe(_bg_loop.stop)


def get_mcp_tools() -> list[Tool]:
    """Return the list of MCP tools registered at startup."""
    return list(_mcp_tools)
