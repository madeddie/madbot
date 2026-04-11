# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the bot

```bash
cp .env.example .env   # then fill in TELEGRAM_BOT_TOKEN and OPENCODE_API_KEY
uv sync
uv run madbot
```

## Architecture

The bot is an aiogram v3 Telegram bot with an LLM fallback. All non-command text is routed to an AI provider.

### Handler auto-discovery

`bot/main.py` uses `pkgutil.iter_modules` to load every module in `bot/handlers/` automatically. Any module that exposes a `router = Router()` is registered with the dispatcher. `fallback.py` is always loaded last (hard-coded exception) so command handlers take priority.

**To add a command**: create `bot/handlers/mycommand.py` with a `router = Router()` and handlers. No other file needs to change.

To have the command appear in `/help`, also define a module-level `COMMANDS` dict: `COMMANDS = {"mycommand": "Description shown in /help"}`. `/help` scans all handler modules for this dict at call time.

To expose the command's logic to the AI as a callable tool, define `AI_TOOLS: list[Tool]` using `ai_sdk.tool()`. Extract the business logic into a plain function and reference it from both the tool definition and the aiogram handler. `chat.py` scans all handler modules for `AI_TOOLS` at startup and passes them to every `generate_text` call.

### AI provider layer

`bot/ai/providers.py` exposes two factory functions:
- `opencodego(model_id)` — OpenCode Go endpoint (`https://opencode.ai/zen/go/v1`)
- `opencodezen(model_id)` — OpenCode Zen endpoint (`https://opencode.ai/zen/v1`)

Both auto-select the right `ai_sdk` factory (OpenAI vs Anthropic) based on model ID prefix, using ordered prefix maps `_GO_PREFIX_MAP` / `_ZEN_PREFIX_MAP`. To add support for a new model family, add one tuple to the relevant map.

Endpoint routing by prefix:
- **Go**: `minimax-*` → Anthropic; everything else → OpenAI chat
- **Zen**: `claude-*` → Anthropic; `gpt-*` → OpenAI responses; `gemini-*` → not yet supported; everything else → OpenAI chat

`generate_text` from `ai_sdk` is synchronous; `bot/ai/chat.py` runs it via `asyncio.to_thread` to avoid blocking the event loop. History is stored as `CoreUserMessage` / `CoreAssistantMessage` objects (from `ai_sdk.types`) — plain dicts will not work.

### Configuration

All config lives in `bot/config.py` as a pydantic-settings `Settings` singleton. Key vars: `TELEGRAM_BOT_TOKEN`, `OPENCODE_API_KEY`, `AI_PROVIDER` (`opencodego` or `opencodezen`), `AI_MODEL`, `SYSTEM_PROMPT`, `MAX_HISTORY_MESSAGES`.

### Conversation history

Per-user history is an in-memory `dict[int, list[AnyMessage]]` keyed by Telegram `user_id`. It resets on bot restart. `/start` clears a user's history via `bot.ai.chat.clear_history()`.
