import asyncio
import importlib
import logging
import pkgutil
import sys

import bot.handlers as _handlers_pkg
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.config import settings

logger = logging.getLogger(__name__)


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
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stdout,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = create_dispatcher()

    logger.info(
        "Starting madbot (provider=%s model=%s)",
        settings.ai_provider,
        settings.ai_model,
    )
    try:
        await dp.start_polling(bot, drop_pending_updates=True)
    finally:
        await bot.session.close()


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
