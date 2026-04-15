# AGENTS.md

Quick reference for agents working in this repo. See `CLAUDE.md` for full architecture docs.

## Run the bot

```bash
cp .env.example .env  # fill in TELEGRAM_BOT_TOKEN, OPENCODE_API_KEY
uv sync
uv run madbot
```

## Key conventions agents would miss

- **Handler auto-discovery**: Add new handlers to `bot/handlers/` — do NOT edit `main.py`. Any module with `router = Router()` is auto-loaded.
- **fallback.py loads last**: Hard-coded in `main.py` so command handlers take priority over AI fallback.
- **Owner checks**: Use `message.from_user.id == settings.OWNER_CHAT_ID` — not a decorator.
- **Telegram message limit**: 4096 chars max. Chunk long responses (see `amazon.py` for example).
- **`md_to_tg()` required**: Always convert Markdown with `utils.md_to_tg()` before sending with `parse_mode="MarkdownV2"`.

## AI tool patterns

- Static tools: `AI_TOOLS: list[Tool]` at module level, discovered once at startup.
- Dynamic tools: `make_*_tools(user_id)` factory functions, called per-request.
- Use `asyncio.to_thread()` when calling sync `generate_text` from async handlers.

## Config

All settings in `bot/config.py` via pydantic-settings. Required env vars: `TELEGRAM_BOT_TOKEN`, `OPENCODE_API_KEY`.

## No test framework

No tests directory or test config found. Manual verification only.