# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the bot

```bash
cp .env.example .env   # then fill in required variables (see Configuration)
uv sync
uv run madbot
```

## Project structure

```
bot/
├── ai/
│   ├── chat.py        # Conversation history, tool collection, generate_text wrappers
│   └── providers.py   # AI model factory functions and endpoint routing
├── handlers/          # Auto-discovered handler modules (one per feature)
│   ├── admin.py       # Owner-only: /quit, /restart, /gitpull
│   ├── amazon.py      # /orders — Amazon order tracking
│   ├── briefing.py    # /briefing — personalized daily briefing
│   ├── echo.py        # /echo — repeats text
│   ├── facts.py       # /facts — user fact store (key/value)
│   ├── fallback.py    # Catches all non-command text → AI chat
│   ├── fetch.py       # AI tool: fetch_webpage
│   ├── help.py        # /help — auto-generated command list
│   ├── introspect.py  # AI tools: logs, source files, bot status (owner only)
│   ├── news.py        # AI tool: get_news_headlines
│   ├── schedule.py    # /schedule — APScheduler job management
│   ├── search.py      # AI tool: web_search (DuckDuckGo)
│   ├── start.py       # /start — clears conversation history
│   ├── time.py        # /time + AI tool: get_time
│   └── weather.py     # /weather + AI tools: get_weather, get_weather_forecast
├── config.py          # pydantic-settings Settings singleton
├── db.py              # SQLite database (facts table)
├── main.py            # Entry point, dispatcher setup, handler auto-discovery
├── scheduler.py       # APScheduler wrapper with SQLAlchemy job store
└── utils.py           # md_to_tg() Markdown → Telegram MarkdownV2 conversion
```

## Architecture

The bot is an aiogram v3 Telegram bot with an LLM fallback. All non-command text is routed to an AI provider.

### Handler auto-discovery

`bot/main.py` uses `pkgutil.iter_modules` to load every module in `bot/handlers/` automatically. Any module that exposes a `router = Router()` is registered with the dispatcher. `fallback.py` is always loaded last (hard-coded exception) so command handlers take priority.

**To add a command**: create `bot/handlers/mycommand.py` with a `router = Router()` and handlers. No other file needs to change.

To have the command appear in `/help`, also define a module-level `COMMANDS` dict:
```python
COMMANDS = {"mycommand": "Description shown in /help"}
```
`/help` scans all handler modules for this dict at call time.

To expose the command's logic to the AI as a callable tool, define `AI_TOOLS: list[Tool]` using `ai_sdk.tool()`. Extract the business logic into a plain function and reference it from both the tool definition and the aiogram handler. `chat.py` scans all handler modules for `AI_TOOLS` at startup and passes them to every `generate_text` call.

### Two patterns for AI tools

**Static tools** — module-level list, collected once at startup:
```python
AI_TOOLS: list[Tool] = [
    ai_sdk.tool(name="my_tool", description="...", parameters={...}, execute=_my_fn),
]
```

**Dynamic tools** — factory functions named `make_*_tools(user_id)`, called per-user to bind user context (e.g. user's timezone, user_id for database writes):
```python
def make_mything_tools(user_id: int) -> list[Tool]:
    def _do_thing():
        # can close over user_id
        ...
    return [ai_sdk.tool(name="do_thing", ..., execute=_do_thing)]
```
`chat.py` discovers any function matching `make_*_tools` in handler modules and calls it with the user's id for each request.

### AI provider layer

`bot/ai/providers.py` exposes two factory functions:
- `opencodego(model_id)` — OpenCode Go endpoint (`https://opencode.ai/zen/go/v1`)
- `opencodezen(model_id)` — OpenCode Zen endpoint (`https://opencode.ai/zen/v1`)

Both auto-select the right `ai_sdk` factory (OpenAI vs Anthropic) based on model ID prefix, using ordered prefix maps `_GO_PREFIX_MAP` / `_ZEN_PREFIX_MAP`. To add support for a new model family, add one tuple to the relevant map.

Endpoint routing by prefix:
- **Go**: `minimax-*` → Anthropic; everything else → OpenAI chat
- **Zen**: `claude-*` → Anthropic; `gpt-*` → OpenAI responses; `gemini-*` → not yet supported; everything else → OpenAI chat

`generate_text` from `ai_sdk` is synchronous; `bot/ai/chat.py` runs it via `asyncio.to_thread` to avoid blocking the event loop. History is stored as `CoreUserMessage` / `CoreAssistantMessage` objects (from `ai_sdk.types`) — plain dicts will not work.

### AI chat functions

`bot/ai/chat.py` provides three public functions:
- `chat(user_id, user_message)` — multi-turn conversation, maintains per-user history
- `one_shot(user_id, query, extra_system)` — single isolated call, no history side-effects
- `run_scheduled_query(user_id, query)` — used by scheduler; calls `one_shot` then sends result via `bot.send_message()`
- `clear_history(user_id)` — wipes a user's conversation history

System prompt is assembled by `_build_system(user_id, extra)`: base prompt + user facts from DB + optional extra suffix.

### Configuration

All config lives in `bot/config.py` as a pydantic-settings `Settings` singleton. Environment variables:

| Variable | Required | Default | Description |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | yes | — | Bot token from @BotFather |
| `OPENCODE_API_KEY` | yes | — | API key for OpenCode endpoints |
| `AI_PROVIDER` | no | `opencodego` | `opencodego` or `opencodezen` |
| `AI_MODEL` | no | `glm-5.1` | Model ID string |
| `SYSTEM_PROMPT` | no | `""` | Base system instruction for AI |
| `MAX_HISTORY_MESSAGES` | no | `20` | Per-user history limit (1–200) |
| `DB_PATH` | no | `madbot.db` | SQLite database file path |
| `DEBUG` | no | `false` | Enable DEBUG log level |
| `LOG_FILE` | no | `""` | Optional file path for log output |
| `OWNER_CHAT_ID` | no | `0` | Telegram user_id for owner-only commands |
| `AMAZON_USERNAME` | no | `""` | Amazon login email |
| `AMAZON_PASSWORD` | no | `""` | Amazon login password |
| `AMAZON_OTP_SECRET` | no | `""` | Amazon TOTP secret (optional) |

### Conversation history

Per-user history is an in-memory `dict[int, list[AnyMessage]]` keyed by Telegram `user_id`. It resets on bot restart. `/start` clears a user's history via `bot.ai.chat.clear_history()`.

### Database

`bot/db.py` manages a SQLite database (path from `DB_PATH` setting). Two uses:

1. **Facts table** — user key/value store, schema: `(user_id INTEGER, key TEXT, value TEXT)` with composite primary key.
   - `get_facts(user_id)` → `dict[str, str]`
   - `set_fact(user_id, key, value)` — upsert
   - `remove_fact(user_id, key)` → `bool`
   - Facts are automatically injected into the AI system prompt per user.

2. **APScheduler job store** — persists scheduled tasks across restarts (via SQLAlchemy backend).

### Scheduler

`bot/scheduler.py` wraps APScheduler's `AsyncIOScheduler` with a SQLAlchemy job store backed by the same SQLite database.

- `init(bot)` — must be called inside the running event loop (called from aiogram startup hook)
- `_run_scheduled_job(user_id, query)` — job callback; fires `run_scheduled_query()` from `chat.py`
- Jobs are stored with user_id embedded in the job id for per-user listing/cancellation

### Markdown conversion

`bot/utils.py` exports `md_to_tg(text)` which converts standard Markdown to Telegram MarkdownV2 format via `telegramify_markdown`. Always use this when sending AI-generated text to Telegram with `parse_mode="MarkdownV2"`.

## Handler reference

| Handler | Slash commands | AI tools |
|---|---|---|
| `admin.py` | `/quit`, `/restart`, `/gitpull` (owner only) | — |
| `amazon.py` | `/orders` | `list_amazon_orders` |
| `briefing.py` | `/briefing` | `configure_briefing` (factory) |
| `echo.py` | `/echo` | `echo` |
| `facts.py` | `/facts [set\|remove]` | `set_fact`, `remove_fact`, `list_facts` (factory) |
| `fallback.py` | — | — |
| `fetch.py` | — | `fetch_webpage` |
| `help.py` | `/help` | — |
| `introspect.py` | — | `get_recent_logs`, `list_source_files`, `read_source_file`, `get_bot_status` (factory, owner only) |
| `news.py` | — | `get_news_headlines` |
| `schedule.py` | `/schedule [list\|cancel]` | `schedule_once`, `schedule_recurring`, `list_schedules`, `cancel_schedule` (factory) |
| `search.py` | — | `web_search` |
| `start.py` | `/start` | — |
| `time.py` | `/time` | `get_time` |
| `weather.py` | `/weather [forecast]` | `get_weather`, `get_weather_forecast` |

## Key conventions

- **Business logic separation**: extract logic into a plain `_function()`, then reference it from both the aiogram handler and the `ai_sdk.tool()` definition. This avoids duplication.
- **Owner-only checks**: compare `message.from_user.id == settings.OWNER_CHAT_ID`. Introspect tools return an empty list from the factory if the user isn't the owner.
- **Async vs sync**: aiogram handlers are `async def`; `generate_text` is sync — always wrap in `asyncio.to_thread()`.
- **Telegram message limits**: Telegram caps messages at 4096 characters. Chunk long responses manually (see `amazon.py`).
- **No manual registration**: never edit `main.py` to add new handlers — the auto-discovery handles it.
- **Path safety in introspect**: `read_source_file` sandboxes paths to the project root and whitelists `.py`, `.md`, `.toml` extensions.
