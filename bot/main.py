import asyncio
import importlib
import logging
import pkgutil
import sys
from datetime import datetime, timezone

import bot.handlers as _handlers_pkg
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from bot.config import settings

logger = logging.getLogger(__name__)

start_time: datetime = datetime.now(timezone.utc)


def create_dispatcher() -> Dispatcher:
    dp = Dispatcher()

    # Auto-discover all handler modules, load non-fallback ones first.
    for mod_info in pkgutil.iter_modules(_handlers_pkg.__path__):
        if mod_info.name == "fallback":
            continue
        mod = importlib.import_module(f"bot.handlers.{mod_info.name}")
        if hasattr(mod, "router"):
            dp.include_router(mod.router)
            logger.debug("Loaded handler: %s", mod_info.name)

    # Fallback must be last — it catches all remaining F.text messages.
    from bot.handlers import fallback

    dp.include_router(fallback.router)

    return dp


async def _main() -> None:
    log_level = logging.DEBUG if settings.debug else logging.INFO
    log_fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(
        level=log_level,
        stream=sys.stdout,
        format=log_fmt,
    )
    if settings.log_file:
        file_handler = logging.FileHandler(settings.log_file)
        file_handler.setFormatter(logging.Formatter(log_fmt))
        file_handler.setLevel(log_level)
        logging.getLogger().addHandler(file_handler)

    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    from bot import db as _db_mod

    _db_mod.init()

    from bot import scheduler as _scheduler_mod

    _scheduler_mod.init(bot)

    from bot.ai import mcp_client as _mcp_mod
    from pathlib import Path

    await _mcp_mod.init(Path(settings.mcp_config_path))

    dp = create_dispatcher()

    logger.info(
        "Starting madbot (provider=%s model=%s)",
        settings.ai_provider,
        settings.ai_model,
    )

    async def _on_startup(bot: Bot, **kwargs) -> None:
        commands: dict[str, str] = {}
        for mod_info in pkgutil.iter_modules(_handlers_pkg.__path__):
            mod = importlib.import_module(f"bot.handlers.{mod_info.name}")
            if hasattr(mod, "COMMANDS"):
                commands.update(mod.COMMANDS)
        await bot.set_my_commands(
            [BotCommand(command=cmd, description=desc) for cmd, desc in sorted(commands.items())]
        )

        if settings.owner_chat_id:
            await bot.send_message(settings.owner_chat_id, "madbot is online.")

    dp.startup.register(_on_startup)

    try:
        await dp.start_polling(bot, drop_pending_updates=True)
    finally:
        _scheduler_mod.get_scheduler().shutdown(wait=False)
        await _mcp_mod.shutdown()
        await bot.session.close()


def main() -> None:
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
