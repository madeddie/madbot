import logging

from aiogram import Bot
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.config import settings

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None
_bot: Bot | None = None


def init(bot: Bot) -> None:
    """Initialise the scheduler. Must be called inside a running asyncio event loop."""
    global _scheduler, _bot
    _bot = bot
    _scheduler = AsyncIOScheduler(
        jobstores={"default": SQLAlchemyJobStore(url=f"sqlite:///{settings.scheduler_db_path}")},
        job_defaults={"misfire_grace_time": 60},
    )
    _scheduler.start()
    logger.info("Scheduler started (db=%s)", settings.scheduler_db_path)


def get_scheduler() -> AsyncIOScheduler:
    if _scheduler is None:
        raise RuntimeError("Scheduler not initialised. Call scheduler.init(bot) first.")
    return _scheduler


def get_bot() -> Bot:
    if _bot is None:
        raise RuntimeError("Bot not set in scheduler.")
    return _bot


async def _run_scheduled_job(user_id: int, query: str) -> None:
    """Fired by APScheduler when a job is due. Runs an isolated AI query and sends the result."""
    from bot.ai.chat import run_scheduled_query  # late import — avoids circular at module level
    await run_scheduled_query(user_id, query)
